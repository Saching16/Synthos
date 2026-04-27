"""POST /handbook (SSE) and handbook downloads (Phase 9)."""

from __future__ import annotations

import asyncio
import html
import json
import logging
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

import asyncpg
import markdown
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, Response
from sse_starlette import ServerSentEvent
from sse_starlette.sse import EventSourceResponse
from weasyprint import HTML as WeasyHTML

from app.config import get_settings
from app.db import get_pool
from app.schemas import HandbookOut, HandbookRequest
from app.services.agentwrite import generate_handbook
from app.services.rag import handbook_context

logger = logging.getLogger(__name__)

router = APIRouter(tags=["handbook"])


async def _ensure_documents_exist(pool: asyncpg.Pool, doc_ids: list[UUID]) -> None:
    if not doc_ids:
        return
    async with pool.acquire() as conn:
        n = await conn.fetchval(
            "SELECT count(*)::int FROM documents WHERE id = ANY($1::uuid[])",
            doc_ids,
        )
    if int(n or 0) != len(doc_ids):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="One or more document_ids do not exist",
        )


@router.post("/handbook")
async def handbook_sse(
    request: Request,
    body: HandbookRequest,
    pool: asyncpg.Pool | None = Depends(get_pool),
) -> EventSourceResponse:
    if pool is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured (set SUPABASE_DB_URL)",
        )
    topic = body.topic.strip()
    doc_id_strs: list[str] | None = (
        [str(x) for x in body.document_ids] if body.document_ids else None
    )
    await _ensure_documents_exist(pool, list(body.document_ids or []))

    settings = get_settings()
    hb_id = uuid4()

    async def retrieve(q: str) -> str:
        return await handbook_context(q, doc_id_strs)

    async def event_gen():
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        async def on_event(payload: dict[str, object]) -> bool:
            if await request.is_disconnected():
                logger.info("handbook run cancelled (client disconnected)")
                return False
            await queue.put(payload)
            return True

        async def runner() -> None:
            try:
                md = await generate_handbook(
                    topic,
                    on_event=on_event,
                    retrieve_context=retrieve,
                )
                await queue.put({"type": "__done__", "markdown": md})
            except Exception:
                logger.exception("handbook generation failed")
                await queue.put({"type": "__error__"})
            finally:
                await queue.put(None)

        task = asyncio.create_task(runner())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if item.get("type") == "__error__":
                    yield ServerSentEvent(
                        event="error",
                        data=json.dumps(
                            {"message": "Handbook generation failed."},
                            ensure_ascii=False,
                        ),
                    )
                    break
                if item.get("type") == "__done__":
                    md = str(item.get("markdown") or "")
                    settings.handbooks_path.mkdir(parents=True, exist_ok=True)
                    rel_name = f"{hb_id}.md"
                    fp = settings.handbooks_path / rel_name
                    fp.write_text(md, encoding="utf-8")
                    words = len(md.split())
                    path_value = str(Path(settings.handbooks_dir) / rel_name)
                    async with pool.acquire() as conn:
                        await conn.execute(
                            """
                            INSERT INTO handbooks (id, topic, words, path)
                            VALUES ($1, $2, $3, $4)
                            """,
                            hb_id,
                            topic,
                            words,
                            path_value,
                        )
                    yield ServerSentEvent(
                        event="done",
                        data=json.dumps(
                            {
                                "id": str(hb_id),
                                "words": words,
                                "topic": topic,
                            },
                            ensure_ascii=False,
                        ),
                    )
                    break
                ev = str(item.get("type", "message"))
                yield ServerSentEvent(
                    event=ev,
                    data=json.dumps(item, ensure_ascii=False),
                )
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    return EventSourceResponse(event_gen())


def _handbook_file_path(handbook_id: UUID) -> Path:
    return get_settings().handbooks_path / f"{handbook_id}.md"


@router.get("/handbook/{handbook_id}", response_model=HandbookOut)
async def get_handbook(
    handbook_id: UUID,
    pool: asyncpg.Pool | None = Depends(get_pool),
) -> HandbookOut:
    if pool is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured (set SUPABASE_DB_URL)",
        )
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, topic, words, path, created_at
            FROM handbooks
            WHERE id = $1
            """,
            handbook_id,
        )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Handbook not found")
    return HandbookOut(
        id=row["id"],
        topic=row["topic"],
        words=row["words"],
        path=row["path"],
        created_at=row["created_at"],
    )


@router.get("/handbook/{handbook_id}/download")
async def download_handbook(
    handbook_id: UUID,
    fmt: Annotated[
        Literal["md", "pdf"],
        Query(alias="format"),
    ],
    pool: asyncpg.Pool | None = Depends(get_pool),
) -> Response:
    if pool is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured (set SUPABASE_DB_URL)",
        )
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, topic FROM handbooks WHERE id = $1",
            handbook_id,
        )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Handbook not found")

    path = _handbook_file_path(handbook_id)
    if not path.is_file():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Handbook file missing on disk",
        )
    topic = str(row["topic"])
    safe_name = (
        "".join(c if c.isalnum() or c in " -_" else "_" for c in topic)[:80].strip()
        or "handbook"
    )

    if fmt == "md":
        return FileResponse(
            path,
            media_type="text/markdown; charset=utf-8",
            filename=f"{safe_name}.md",
        )

    md = path.read_text(encoding="utf-8")
    html_body = markdown.markdown(
        md,
        extensions=["extra", "fenced_code", "tables", "nl2br"],
    )
    title_html = html.escape(topic[:200])
    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>{title_html}</title>
<style>
body {{ font-family: Georgia, serif; margin: 2rem; line-height: 1.45; }}
h1, h2, h3, h4 {{ page-break-after: avoid; }}
pre, code {{ font-family: ui-monospace, monospace; white-space: pre-wrap; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: 0.25rem 0.5rem; }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""
    pdf_bytes = WeasyHTML(string=html_doc).write_pdf()
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}.pdf"',
        },
    )
