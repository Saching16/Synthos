"""POST /chat — SSE stream with RAG context (Phase 7)."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request, status
from sse_starlette import ServerSentEvent
from sse_starlette.sse import EventSourceResponse

from app.schemas import ChatRequest
from app.services.chat_intent import extract_handbook_topic, is_handbook_request
from app.services.llm import LlmClient
from app.services.rag import query as rag_query

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

_SYSTEM_RAG = """You are a helpful assistant. Use the retrieved context and the prior conversation when answering.

## Retrieved context
{context}

If the context does not contain enough information, say so clearly. Answer the user's latest message."""


def _messages_for_llm(
    *,
    context: str,
    history: list[tuple[str, str]],
    user_message: str,
) -> list[dict[str, str]]:
    system = _SYSTEM_RAG.format(context=context or "(No context was retrieved.)")
    out: list[dict[str, str]] = [{"role": "system", "content": system}]
    for role, content in history:
        c = (content or "").strip()
        if not c:
            continue
        out.append({"role": role, "content": c})
    out.append({"role": "user", "content": user_message.strip()})
    return out


async def _normalize_rag_context(raw: str | AsyncIterator[str]) -> str:
    if isinstance(raw, str):
        return raw
    parts: list[str] = []
    async for piece in raw:
        parts.append(piece)
    return "".join(parts)


@router.post("/chat")
async def chat_sse(request: Request, body: ChatRequest) -> EventSourceResponse:
    msg = body.message.strip()
    if not msg:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="message must not be empty",
        )

    async def event_gen():
        if await request.is_disconnected():
            return

        if is_handbook_request(msg):
            topic = extract_handbook_topic(msg)
            payload = {
                "path": "/handbook",
                "topic": topic,
                "message": (
                    "Opening the handbook workspace so you can generate a long-form guide."
                ),
            }
            yield ServerSentEvent(
                event="redirect",
                data=json.dumps(payload, ensure_ascii=False),
            )
            yield ServerSentEvent(event="done", data="{}")
            return

        try:
            raw_ctx = await rag_query(
                msg,
                mode="hybrid",
                only_need_context=True,
            )
            context = await _normalize_rag_context(raw_ctx)
        except Exception:
            logger.exception("RAG context retrieval failed for chat")
            context = "(RAG retrieval failed; answer without uploaded documents.)"

        history_pairs: list[tuple[str, str]] = [
            (m.role, m.content) for m in body.history if (m.content or "").strip()
        ]
        messages = _messages_for_llm(
            context=context,
            history=history_pairs,
            user_message=msg,
        )
        llm = LlmClient()
        try:
            async for delta in llm.stream_messages(
                messages,
                max_tokens=4096,
                temperature=0.5,
            ):
                if await request.is_disconnected():
                    logger.warning("client disconnected during chat stream")
                    return
                if delta:
                    yield ServerSentEvent(
                        event="token",
                        data=json.dumps({"text": delta}, ensure_ascii=False),
                    )
        except Exception:
            logger.exception("LLM stream failed for chat")
            yield ServerSentEvent(
                event="error",
                data=json.dumps(
                    {"message": "The language model request failed."},
                    ensure_ascii=False,
                ),
            )
        yield ServerSentEvent(event="done", data="{}")

    return EventSourceResponse(event_gen())
