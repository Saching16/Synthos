"""Typed settings loaded from environment and optional `backend/.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_bool(v: object) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


class Settings(BaseSettings):
    """Application configuration. Required keys must be set before the app starts."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_nested_delimiter="__",
    )

    openrouter_api_key: str = Field(
        ...,
        min_length=1,
        description="OpenRouter API key (chat + embeddings via OpenAI-compatible API)",
    )
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Default: Free Models Router — zero-cost chat; swap for a specific model id if you prefer.
    openrouter_chat_model: str = "openrouter/free"
    # Embeddings use the same API key; pick any embedding model OpenRouter exposes (may be paid per token).
    openrouter_embed_model: str = "openai/text-embedding-3-small"
    # Vector size for OpenRouter embedding model (text-embedding-3-small → 1536).
    openrouter_embedding_dim: int = 1536
    # Optional attribution headers recommended by OpenRouter (https://openrouter.ai/docs)
    openrouter_http_referer: str | None = None
    openrouter_app_title: str = "Handbook Generator"

    supabase_db_url: str | None = None
    # Direct Postgres (db.*.supabase.co:5432) for LightRAG when SUPABASE_DB_URL uses the pooler (:6543).
    supabase_direct_db_url: str | None = None
    # Resolve db.*.supabase.co to an IPv4 literal (AF_INET, then dig A). Use after Supabase IPv4 add-on
    # or on networks where IPv6 to Supabase fails (errno 65).
    supabase_postgres_prefer_ipv4: bool = False

    @field_validator("supabase_postgres_prefer_ipv4", mode="before")
    @classmethod
    def _coerce_supabase_postgres_prefer_ipv4(cls, v: object) -> bool:
        return _env_bool(v)

    @field_validator("supabase_db_url", mode="before")
    @classmethod
    def empty_supabase_url(cls, v: object) -> str | None:
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        return str(v).strip()

    @field_validator("supabase_direct_db_url", mode="before")
    @classmethod
    def empty_supabase_direct_url(cls, v: object) -> str | None:
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        return str(v).strip()

    supabase_url: str | None = None
    supabase_service_key: str | None = None

    lightrag_working_dir: str = ".lightrag"
    handbooks_dir: str = ".handbooks"
    # When true, plan/write/expand LLM responses are stored under
    # ``{handbooks_dir}/.agentwrite_cache`` keyed by prompt + model + context.
    agentwrite_cache_enabled: bool = True

    cors_origins: str = "http://localhost:5173"
    # Base URL for markdown citation links in handbooks (GET /documents/{id}/page/{n}).
    api_public_url: str = "http://localhost:8000"

    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def log_level_upper(cls, v: str) -> str:
        return v.upper()

    @field_validator("agentwrite_cache_enabled", mode="before")
    @classmethod
    def _coerce_agentwrite_cache_enabled(cls, v: object) -> bool:
        return _env_bool(v)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def lightrag_working_path(self) -> Path:
        return Path(self.lightrag_working_dir).resolve()

    @property
    def handbooks_path(self) -> Path:
        return Path(self.handbooks_dir).resolve()

    @property
    def lightrag_postgres_dsn(self) -> str | None:
        return self.supabase_direct_db_url or self.supabase_db_url

    @property
    def openrouter_default_headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.openrouter_http_referer:
            h["HTTP-Referer"] = self.openrouter_http_referer
        if self.openrouter_app_title:
            h["X-Title"] = self.openrouter_app_title
        return h


@lru_cache
def get_settings() -> Settings:
    return Settings()
