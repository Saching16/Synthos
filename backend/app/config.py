"""Typed settings loaded from environment and optional `backend/.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # Optional attribution headers recommended by OpenRouter (https://openrouter.ai/docs)
    openrouter_http_referer: str | None = None
    openrouter_app_title: str = "Handbook Generator"

    supabase_db_url: str | None = None
    supabase_url: str | None = None
    supabase_service_key: str | None = None

    lightrag_working_dir: str = ".lightrag"

    cors_origins: str = "http://localhost:5173"

    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def log_level_upper(cls, v: str) -> str:
        return v.upper()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def lightrag_working_path(self) -> Path:
        return Path(self.lightrag_working_dir).resolve()

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
