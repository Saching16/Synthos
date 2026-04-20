"""asyncpg pool lifecycle and health check helpers."""

from __future__ import annotations

import ipaddress
import logging
import ssl
from typing import Any
from urllib.parse import quote, unquote, urlparse

import asyncpg
from fastapi import Request

logger = logging.getLogger(__name__)

_PG_PREFIX = "postgresql://"


def normalize_postgres_dsn(dsn: str) -> str:
    """
    Make a libpq URI safe for urllib/asyncpg (Python 3.12+ is strict).

    Supabase pooler/direct hosts use ``...@aws-...`` or ``...@db.<ref>.supabase.co``.
    Passwords with ``@``, ``:``, ``[``, etc. must be percent-encoded or ``urlparse`` and
    asyncpg can raise ``ValueError`` before any network I/O.

    For those hosts we always rebuild userinfo with ``quote(unquote(password))``.
    """
    dsn = dsn.strip()
    if not dsn.startswith(_PG_PREFIX):
        return dsn

    cut = None
    for marker in ("@aws-", "@db."):
        p = dsn.find(marker)
        if p > 0:
            cut = p
            break
    if cut is None:
        return dsn

    creds = dsn[len(_PG_PREFIX) : cut]
    host_and_rest = dsn[cut + 1 :]  # host:port/db?query
    if ":" not in creds:
        return dsn
    user, password = creds.split(":", 1)
    encoded = quote(unquote(password), safe="")
    return f"{_PG_PREFIX}{user}:{encoded}@{host_and_rest}"


def _dsn_host_is_ip_literal(dsn: str) -> bool:
    u = urlparse(normalize_postgres_dsn(dsn.strip()))
    h = u.hostname
    if not h:
        return False
    try:
        ipaddress.ip_address(h.strip("[]").split("%", 1)[0])
        return True
    except ValueError:
        return False


async def create_pool(dsn: str) -> asyncpg.Pool:
    dsn = normalize_postgres_dsn(dsn)
    # Transaction pooler (PgBouncer, port 6543): prepared statements break; disable cache.
    # Safe for direct Postgres (5432) too; small perf tradeoff.
    ssl_ctx: ssl.SSLContext | None = None
    if _dsn_host_is_ip_literal(dsn):
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        logger.warning(
            "asyncpg pool: TLS verify disabled (host is an IP literal; cert is for db hostname)"
        )
    kw: dict[str, Any] = {
        "dsn": dsn,
        "min_size": 1,
        "max_size": 10,
        "statement_cache_size": 0,
        # Avoid hung clients when Supabase or the network stalls mid-query.
        "command_timeout": 60,
    }
    if ssl_ctx is not None:
        kw["ssl"] = ssl_ctx
    return await asyncpg.create_pool(**kw)


async def close_pool(pool: asyncpg.Pool | None) -> None:
    if pool is not None:
        await pool.close()


def get_pool(request: Request) -> asyncpg.Pool | None:
    """FastAPI dependency: Postgres pool, or None if `SUPABASE_DB_URL` was not set."""
    return getattr(request.app.state, "db_pool", None)


async def db_status(pool: asyncpg.Pool | None) -> str:
    """
    Return connection status for /health:
    not_configured — no SUPABASE_DB_URL
    ok — SELECT 1 succeeded
    down — pool missing connection or query failed
    """
    if pool is None:
        return "not_configured"
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return "ok"
    except Exception:
        logger.exception("database health check failed")
        return "down"
