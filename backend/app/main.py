"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request

from app.config import get_settings
from app.db import close_pool, create_pool, db_status
from app.logging_config import setup_logging
from app.middleware import RequestLoggingMiddleware
from app.services.rag import (
    rewrite_supabase_dsn_tcp_host,
    shutdown_rag,
    startup_rag,
)

logger = logging.getLogger(__name__)

# If Supabase is unreachable, do not hang /health forever (curl would look "stuck").
_HEALTH_DB_TIMEOUT_S = 5.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    app.state.db_pool = None
    if settings.supabase_db_url:
        pool_dsn = rewrite_supabase_dsn_tcp_host(
            settings.supabase_db_url,
            settings.supabase_postgres_prefer_ipv4,
        )
        app.state.db_pool = await create_pool(pool_dsn)
    try:
        try:
            await startup_rag()
        except Exception:
            logger.exception(
                "LightRAG initialization failed; server continues without RAG"
            )
        yield
    finally:
        await shutdown_rag()
        await close_pool(getattr(app.state, "db_pool", None))


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Handbook Generator API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health(request: Request) -> dict[str, str]:
        pool = getattr(request.app.state, "db_pool", None)
        try:
            db = await asyncio.wait_for(
                db_status(pool),
                timeout=_HEALTH_DB_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "database health check timed out after %ss",
                _HEALTH_DB_TIMEOUT_S,
            )
            db = "timeout"
        return {
            "status": "ok",
            "db": db,
        }

    return app


app = create_app()
