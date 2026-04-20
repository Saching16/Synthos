"""Phase 5 smoke: insert a snippet and retrieve context (expects Paris).

Uses ``naive`` query mode so the check passes when chunk vectors are stored,
even if the chat model fails LightRAG's strict entity/relation extraction
(common with ``openrouter/free``). For production ``hybrid`` / graph modes,
set ``OPENROUTER_CHAT_MODEL`` to a model that follows structured prompts
(e.g. ``openai/gpt-4o-mini`` on OpenRouter).
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lightrag import QueryParam  # noqa: E402

from app.services.rag import get_rag  # noqa: E402


async def main() -> None:
    rag = await get_rag()
    # Fresh id each run so a prior failed/cached insert does not skip as duplicate.
    doc_id = f"smoke-{uuid.uuid4().hex[:12]}"
    await rag.ainsert("The capital of France is Paris.", ids=[doc_id])
    ctx = await rag.aquery(
        "What is the capital of France?",
        param=QueryParam(mode="naive", only_need_context=True),
    )
    print(ctx)


if __name__ == "__main__":
    asyncio.run(main())
