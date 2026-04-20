"""LightRAG singleton: Postgres KV + vectors, OpenRouter LLM + embeddings."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
import socket
import ssl
import subprocess
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse, urlunparse

logger = logging.getLogger(__name__)


def _install_pgvector_extensions_schema_patch() -> None:
    """Supabase installs pgvector in ``extensions``; pgvector defaults to ``public``.

    LightRAG calls ``register_vector`` on pool connect; without this, asyncpg
    raises ``unknown type: public.vector``. Run before importing LightRAG.
    """
    import pgvector.asyncpg as _pgv_pkg
    import pgvector.asyncpg.register as _pgv_reg

    if getattr(_pgv_reg.register_vector, "_silverai_extensions_fallback", False):
        return

    _orig = _pgv_reg.register_vector

    async def _register_vector_public_or_extensions(
        conn, schema: str = "public"
    ) -> None:
        try:
            await _orig(conn, schema=schema)
        except ValueError as e:
            msg = str(e)
            if schema == "public" and "unknown type" in msg and "public.vector" in msg:
                logger.info(
                    "pgvector: registering vector codecs in extensions schema (Supabase)"
                )
                await _orig(conn, schema="extensions")
            else:
                raise

    _register_vector_public_or_extensions._silverai_extensions_fallback = True  # type: ignore[attr-defined]
    _pgv_reg.register_vector = _register_vector_public_or_extensions
    # Also rebind the re-export in `pgvector.asyncpg` (bound at __init__ via `from .register import register_vector`).
    _pgv_pkg.register_vector = _register_vector_public_or_extensions
    # And rebind the name LightRAG's Postgres backend captured via `from pgvector.asyncpg import register_vector`.
    try:
        from lightrag.kg import postgres_impl as _lrpg

        _lrpg.register_vector = _register_vector_public_or_extensions
    except ImportError:
        pass


_install_pgvector_extensions_schema_patch()

import numpy as np  # noqa: E402
from lightrag import LightRAG, QueryParam  # noqa: E402
from lightrag.utils import EmbeddingFunc  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services.llm import LlmClient  # noqa: E402
from app.services.openrouter import get_async_openrouter_client  # noqa: E402

_EMBED_BATCH = 64

_rag: LightRAG | None = None
_init_lock = asyncio.Lock()
_llm_client: LlmClient | None = None
_pg_ssl_patch_installed = False


def _llm_singleton() -> LlmClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LlmClient()
    return _llm_client


def _dig_a_ipv4(host: str) -> str | None:
    """Resolve first IPv4 ``A`` record via ``dig`` (session pooler often has A; good on IPv4-only LAN)."""
    if not re.fullmatch(r"[0-9a-zA-Z.-]+", host):
        return None
    try:
        proc = subprocess.run(
            ["dig", "+short", "A", host],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning("dig A fallback failed to run for %s: %s", host, e)
        return None
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        try:
            ipaddress.IPv4Address(line)
        except ValueError:
            continue
        return line
    return None


def _dig_aaaa_ipv6(host: str) -> str | None:
    """Resolve AAAA via ``dig`` when libc ``getaddrinfo`` fails (seen on some macOS setups)."""
    if not re.fullmatch(r"[0-9a-zA-Z.-]+", host):
        return None
    try:
        proc = subprocess.run(
            ["dig", "+short", "AAAA", host],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning("dig AAAA fallback failed to run for %s: %s", host, e)
        return None
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        candidate = line.split("%", 1)[0].strip()
        try:
            ipaddress.IPv6Address(candidate)
        except ValueError:
            continue
        return candidate
    return None


def _ipv4_literal_for_host(host: str, port: int) -> str | None:
    """Return first IPv4 address for ``host`` (libc AF_INET, then ``dig A``)."""
    try:
        infos4 = socket.getaddrinfo(
            host,
            port,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except OSError as e:
        logger.warning("Postgres DNS (AF_INET) failed for %s:%s: %s", host, port, e)
        infos4 = []
    if infos4:
        return infos4[0][4][0]
    return _dig_a_ipv4(host)


def _resolve_postgres_connect_host(
    host: str, port: int, *, prefer_ipv4: bool = False
) -> tuple[str, bool]:
    """Return (host for TCP, connect_via_ip_literal).

    When ``prefer_ipv4`` (Supabase IPv4 add-on or IPv4-only path), resolve an
    IPv4 literal first so libc does not pick an unreachable AAAA.

    Otherwise prefer libc ``getaddrinfo``. If it fails (common on macOS), try
    ``dig`` **A** first (session pooler usually has IPv4), then **AAAA**.
    Connecting by IP requires relaxed TLS (cert is for the hostname).
    """
    if prefer_ipv4:
        v4_first = _ipv4_literal_for_host(host, port)
        if v4_first:
            logger.info(
                "Postgres: prefer-ipv4 using %s for %s (TLS verify relaxed for IP)",
                v4_first,
                host,
            )
            return v4_first, True
    try:
        infos = socket.getaddrinfo(
            host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
    except OSError as e:
        logger.warning(
            "Postgres DNS (AF_UNSPEC) failed for %s:%s: %s",
            host,
            port,
            e,
        )
        infos = []
    if infos:
        fams = sorted({socket.AddressFamily(i[0]).name for i in infos})
        logger.info("Postgres DNS (AF_UNSPEC): %s -> %s", host, fams)
        return host, False
    infos6: list[Any] = []
    try:
        infos6 = socket.getaddrinfo(
            host,
            port,
            family=socket.AF_INET6,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except OSError as e:
        logger.warning(
            "Postgres DNS (AF_INET6-only) failed for %s:%s: %s",
            host,
            port,
            e,
        )
    if infos6:
        ip = infos6[0][4][0]
        if "%" in ip:
            ip = ip.split("%", 1)[0]
        logger.warning(
            "Postgres: using IPv6 literal from getaddrinfo for %s; TLS verify relaxed",
            host,
        )
        return ip, True
    v4 = _dig_a_ipv4(host)
    if v4:
        logger.warning(
            "Postgres: using IPv4 from dig A for %s (%s); libc getaddrinfo failed; TLS verify relaxed",
            host,
            v4,
        )
        return v4, True
    dig_ip = _dig_aaaa_ipv6(host)
    if dig_ip:
        logger.warning(
            "Postgres: using IPv6 from dig AAAA for %s (%s); libc getaddrinfo failed; TLS verify relaxed. "
            "If TCP then fails with errno 65 (No route to host), this network has no IPv6 path — "
            "prefer a Session pooler DSN (often has IPv4) or another network.",
            host,
            dig_ip,
        )
        return dig_ip, True
    return host, False


def _ensure_postgres_env_from_supabase_dsn(
    url: str, *, prefer_ipv4: bool = False
) -> None:
    u = urlparse(url)
    scheme = u.scheme.split("+", 1)[0] if "+" in u.scheme else u.scheme
    if scheme not in ("postgres", "postgresql"):
        raise ValueError(
            f"SUPABASE_DB_URL must be a postgres URL, got scheme={u.scheme!r}"
        )
    orig_host = u.hostname or "localhost"
    port = u.port or 5432
    user = unquote(u.username or "postgres")
    password = unquote(u.password or "")
    database = (u.path or "/postgres").lstrip("/") or "postgres"
    connect_host, ip_literal = _resolve_postgres_connect_host(
        orig_host, port, prefer_ipv4=prefer_ipv4
    )
    # Always apply (not setdefault): LightRAG/dotenv may have left stale POSTGRES_* in os.environ.
    os.environ["POSTGRES_HOST"] = connect_host
    os.environ["POSTGRES_PORT"] = str(port)
    os.environ["POSTGRES_USER"] = user
    os.environ["POSTGRES_PASSWORD"] = password
    os.environ["POSTGRES_DATABASE"] = database
    logger.info(
        "LightRAG Postgres env from DSN: host=%s port=%s user=%s database=%s",
        connect_host,
        port,
        user,
        database,
    )
    qs = parse_qs(u.query)
    sslmode = (qs.get("sslmode") or [None])[0]
    if sslmode and not os.environ.get("POSTGRES_SSL_MODE"):
        os.environ["POSTGRES_SSL_MODE"] = sslmode
    try:
        import certifi

        ca_path = certifi.where()
    except ImportError:
        ca_path = None
    if ca_path and os.path.exists(ca_path):
        os.environ.setdefault("POSTGRES_SSL_ROOT_CERT", ca_path)
    if "supabase.co" in orig_host and not os.environ.get("POSTGRES_SSL_MODE"):
        os.environ.setdefault("POSTGRES_SSL_MODE", "require")
    if ip_literal:
        _install_lightrag_pg_insecure_ssl_patch(force=True)


def _install_lightrag_pg_insecure_ssl_patch(*, force: bool = False) -> None:
    """Relax Postgres TLS verification (dev only).

    Use ``LIGHTRAG_PG_INSECURE_SSL=1``, or ``force=True`` when connecting by
    IP literal from dig fallback (cert is issued for the hostname, not the IP).
    """
    global _pg_ssl_patch_installed
    if _pg_ssl_patch_installed:
        return
    flag = os.environ.get("LIGHTRAG_PG_INSECURE_SSL", "").lower()
    if not force and flag not in ("1", "true", "yes"):
        return
    from lightrag.kg.postgres_impl import PostgreSQLDB

    def _insecure_ssl(self: Any) -> ssl.SSLContext:  # noqa: ANN401
        del self
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        logger.warning(
            "Postgres TLS certificate verification disabled (%s); dev only",
            "IP literal host" if force else "LIGHTRAG_PG_INSECURE_SSL",
        )
        return ctx

    PostgreSQLDB._create_ssl_context = _insecure_ssl  # type: ignore[method-assign]
    os.environ["POSTGRES_SSL_MODE"] = "verify-ca"
    _pg_ssl_patch_installed = True


async def _openrouter_embed(texts: list[str], **kwargs: Any) -> np.ndarray:
    del kwargs
    if not texts:
        return np.zeros((0, get_settings().openrouter_embedding_dim), dtype=np.float32)
    settings = get_settings()
    dim = settings.openrouter_embedding_dim
    client = get_async_openrouter_client()
    all_rows: list[list[float]] = []
    for i in range(0, len(texts), _EMBED_BATCH):
        batch = texts[i : i + _EMBED_BATCH]
        resp = await client.embeddings.create(
            model=settings.openrouter_embed_model,
            input=batch,
        )
        by_index = {d.index: d.embedding for d in resp.data}
        for j in range(len(batch)):
            vec = by_index.get(j)
            if vec is None:
                raise RuntimeError(f"Missing embedding for input index {j}")
            if len(vec) != dim:
                raise RuntimeError(
                    f"Embedding length {len(vec)} != configured openrouter_embedding_dim={dim}"
                )
            all_rows.append(list(vec))
    return np.array(all_rows, dtype=np.float32)


async def llm_model_func(
    prompt: str,
    system_prompt: str | None = None,
    history_messages: list[dict[str, str]] | None = None,
    max_tokens: int | None = None,
    hashing_kv: Any = None,
    **kwargs: Any,
) -> str:
    del hashing_kv, kwargs
    parts: list[str] = []
    if system_prompt:
        parts.append(system_prompt.strip())
        parts.append("")
    if history_messages:
        for m in history_messages:
            role = m.get("role", "user")
            content = (m.get("content") or "").strip()
            parts.append(f"{role}:\n{content}\n")
        parts.append("")
    parts.append(prompt.strip())
    full_prompt = "\n".join(parts).strip()
    mt = max_tokens if max_tokens is not None else 4096
    return await _llm_singleton().complete(
        full_prompt,
        max_tokens=min(int(mt), 8192),
        temperature=0.3,
    )


def rewrite_supabase_dsn_tcp_host(dsn: str, prefer_ipv4: bool) -> str:
    """Rewrite ``postgresql://...@hostname:port/...`` to use an IPv4 literal when requested."""
    from app.db import normalize_postgres_dsn

    dsn = normalize_postgres_dsn(dsn.strip())
    if not prefer_ipv4:
        return dsn
    u = urlparse(dsn)
    host = u.hostname
    if not host:
        return dsn
    try:
        ipaddress.ip_address(host.split("%", 1)[0].strip("[]"))
        return dsn
    except ValueError:
        pass
    port = u.port or 5432
    lit = _ipv4_literal_for_host(host, port)
    if lit is None:
        return dsn
    if u.username is not None:
        uq = quote(unquote(u.username), safe="")
        if u.password is not None:
            pq = quote(unquote(u.password), safe="")
            netloc = f"{uq}:{pq}@{lit}:{port}"
        else:
            netloc = f"{uq}@{lit}:{port}"
    else:
        netloc = f"{lit}:{port}"
    out = urlunparse((u.scheme, netloc, u.path, u.params, u.query, u.fragment))
    return normalize_postgres_dsn(out)


def _build_lightrag() -> LightRAG:
    settings = get_settings()
    dsn = settings.lightrag_postgres_dsn
    if not dsn:
        raise RuntimeError(
            "SUPABASE_DB_URL (or SUPABASE_DIRECT_DB_URL) is required for LightRAG."
        )
    u0 = urlparse(dsn)
    if (
        "pooler.supabase.com" in (u0.hostname or "")
        and (u0.port or 5432) == 6543
        and not settings.supabase_direct_db_url
    ):
        logger.warning(
            "LightRAG with PG storages needs a direct Postgres URL (db.*.supabase.co:5432). "
            "Set SUPABASE_DIRECT_DB_URL from the Supabase dashboard (Session mode is fine; avoid transaction pooler :6543 for vectors)."
        )
    _ensure_postgres_env_from_supabase_dsn(
        dsn, prefer_ipv4=settings.supabase_postgres_prefer_ipv4
    )
    _install_lightrag_pg_insecure_ssl_patch()
    working = str(settings.lightrag_working_path)
    embed = EmbeddingFunc(
        embedding_dim=settings.openrouter_embedding_dim,
        func=_openrouter_embed,
        model_name=settings.openrouter_embed_model,
    )
    return LightRAG(
        working_dir=working,
        llm_model_func=llm_model_func,
        embedding_func=embed,
        kv_storage="PGKVStorage",
        vector_storage="PGVectorStorage",
        llm_model_name=settings.openrouter_chat_model,
        embedding_batch_num=_EMBED_BATCH,
    )


async def get_rag() -> LightRAG:
    global _rag
    async with _init_lock:
        if _rag is None:
            logger.info("Initializing LightRAG (Postgres storages + OpenRouter)")
            instance = _build_lightrag()
            await instance.initialize_storages()
            _rag = instance
            logger.info("LightRAG storages initialized")
    return _rag


async def shutdown_rag() -> None:
    global _rag
    async with _init_lock:
        if _rag is not None:
            await _rag.finalize_storages()
            _rag = None
            logger.info("LightRAG finalized")


async def startup_rag() -> None:
    if get_settings().lightrag_postgres_dsn:
        await get_rag()


async def insert_document(text: str, doc_id: str) -> None:
    rag = await get_rag()
    await rag.ainsert(text, ids=[doc_id])


async def delete_document_by_id(doc_id: str) -> None:
    """Best-effort LightRAG removal for ``doc_id`` (same id used with ``ainsert``)."""
    async with _init_lock:
        rag = _rag
    if rag is None:
        return
    try:
        await rag.adelete_by_doc_id(doc_id)
    except Exception:
        logger.exception("LightRAG adelete_by_doc_id failed for doc_id=%s", doc_id)


async def _scoped_chunks_context(question: str, doc_ids: list[str]) -> str:
    """Vector search over chunk rows restricted to ``full_doc_id`` in ``doc_ids``."""
    rag = await get_rag()
    cv = rag.chunks_vdb
    db = cv.db
    if db is None:
        return ""
    emb = await _openrouter_embed([question.strip()])
    embedding = emb[0].tolist()
    embedding_string = ",".join(map(str, embedding))
    vector_cast = (
        "halfvec"
        if getattr(db, "vector_index_type", None) == "HNSW_HALFVEC"
        else "vector"
    )
    table = cv.table_name
    dist_threshold = 1.0 - cv.cosine_better_than_threshold
    top_k = 40
    sql = f"""
SELECT c.content
FROM {table} c
WHERE c.workspace = $1
  AND c.full_doc_id = ANY($2::varchar[])
  AND c.content_vector <=> '[{embedding_string}]'::{vector_cast} < $3
ORDER BY c.content_vector <=> '[{embedding_string}]'::{vector_cast}
LIMIT $4
"""
    rows = await db.query(
        sql,
        [cv.workspace, doc_ids, dist_threshold, top_k],
        multirows=True,
    )
    if not rows:
        return ""
    parts: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            c = (row.get("content") or "").strip()
        else:
            c = ""
        if c:
            parts.append(c)
    return "\n\n".join(parts)


async def query(
    question: str,
    mode: str = "hybrid",
    only_need_context: bool = False,
    doc_ids: list[str] | None = None,
) -> str | AsyncIterator[str]:
    ids = [x.strip() for x in doc_ids] if doc_ids else []
    if ids:
        scoped = await _scoped_chunks_context(question, ids)
        if scoped.strip():
            return scoped
        logger.warning(
            "Scoped retrieval returned no chunks for doc_ids=%s; falling back to global query",
            ids[:5],
        )
    rag = await get_rag()
    param = QueryParam(mode=mode, only_need_context=only_need_context)
    return await rag.aquery(question, param=param)
