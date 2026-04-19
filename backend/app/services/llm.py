"""Chat completions via OpenRouter with retries, streaming, and usage logging."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TypeVar

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings
from app.logging_config import setup_logging
from app.services.openrouter import get_async_openrouter_client

logger = logging.getLogger("app.services.llm")

_T = TypeVar("_T")

_TRANSIENT_EXC_TYPES: tuple[type[BaseException], ...] = (
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
    InternalServerError,
)


def _before_sleep_log_attempt(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        "llm transient failure; retrying attempt=%s next_wait=%ss exc=%s",
        retry_state.attempt_number,
        getattr(retry_state.next_action, "sleep", 0) if retry_state.next_action else 0,
        exc,
    )


def _transient_chat_retry() -> Callable[
    [Callable[..., Awaitable[_T]]], Callable[..., Awaitable[_T]]
]:
    return retry(
        retry=retry_if_exception_type(_TRANSIENT_EXC_TYPES),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(5),
        before_sleep=_before_sleep_log_attempt,
        reraise=True,
    )


def _context_length_hint(exc: BadRequestError) -> bool:
    body = getattr(exc, "body", None)
    raw = f"{exc!s} {body!r}".lower()
    return any(
        s in raw
        for s in (
            "context_length",
            "context length",
            "maximum context",
            "token limit",
            "too many tokens",
            "exceeds the context",
            "longer than the model",
            "reduce the length",
            "maximum number of tokens",
        )
    )


def _log_llm_call(
    *,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    latency_ms: int,
) -> None:
    logger.info(
        "llm_call model=%s prompt_tokens=%s completion_tokens=%s latency_ms=%s",
        model,
        prompt_tokens if prompt_tokens is not None else "n/a",
        completion_tokens if completion_tokens is not None else "n/a",
        latency_ms,
    )


class LlmClient:
    """OpenRouter-backed chat client (one completion / stream per method call)."""

    def __init__(
        self,
        client: AsyncOpenAI | None = None,
        model: str | None = None,
    ) -> None:
        self._client = client or get_async_openrouter_client()
        self._model = model or get_settings().openrouter_chat_model

    async def complete(
        self,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        @_transient_chat_retry()
        async def _once():
            return await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
                stream=False,
            )

        t0 = time.perf_counter()
        try:
            response = await _once()
        except BadRequestError as e:
            if _context_length_hint(e):
                logger.warning(
                    "llm context-length or token limit error (not retried): %s", e
                )
            raise
        latency_ms = int((time.perf_counter() - t0) * 1000)
        choice = response.choices[0]
        text = (choice.message.content or "").strip()
        u = response.usage
        _log_llm_call(
            model=self._model,
            prompt_tokens=u.prompt_tokens if u else None,
            completion_tokens=u.completion_tokens if u else None,
            latency_ms=latency_ms,
        )
        return text

    async def stream(
        self,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        @_transient_chat_retry()
        async def _open_stream():
            return await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
                stream_options={"include_usage": True},
            )

        t0 = time.perf_counter()
        try:
            stream_resp = await _open_stream()
        except BadRequestError as e:
            if _context_length_hint(e):
                logger.warning(
                    "llm context-length or token limit error (not retried): %s", e
                )
            raise

        usage_prompt: int | None = None
        usage_completion: int | None = None
        try:
            async for chunk in stream_resp:
                if chunk.usage is not None:
                    usage_prompt = chunk.usage.prompt_tokens
                    usage_completion = chunk.usage.completion_tokens
                if chunk.choices:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
        finally:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            _log_llm_call(
                model=self._model,
                prompt_tokens=usage_prompt,
                completion_tokens=usage_completion,
                latency_ms=latency_ms,
            )


async def _run_cli(prompt: str, *, use_stream: bool) -> int:
    llm = LlmClient()
    if use_stream:
        async for piece in llm.stream(prompt):
            sys.stdout.write(piece)
            sys.stdout.flush()
        sys.stdout.write("\n")
    else:
        text = await llm.complete(prompt)
        sys.stdout.write(text + "\n")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke-test OpenRouter chat via LlmClient."
    )
    parser.add_argument("prompt", nargs="?", default="Say hi")
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream tokens to stdout instead of one-shot completion.",
    )
    args = parser.parse_args()
    setup_logging(get_settings().log_level)
    try:
        raise SystemExit(asyncio.run(_run_cli(args.prompt, use_stream=args.stream)))
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
