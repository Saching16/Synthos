"""OpenAI-compatible client pointed at OpenRouter (chat + embeddings)."""

from __future__ import annotations

from openai import AsyncOpenAI

from app.config import get_settings


def get_async_openrouter_client() -> AsyncOpenAI:
    """Shared AsyncOpenAI instance configuration for OpenRouter."""
    s = get_settings()
    headers = s.openrouter_default_headers
    return AsyncOpenAI(
        api_key=s.openrouter_api_key,
        base_url=s.openrouter_base_url,
        default_headers=headers if headers else None,
    )
