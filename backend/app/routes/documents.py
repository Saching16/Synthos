"""GET /documents and DELETE /documents/{id}."""

from __future__ import annotations

import html
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from starlette.responses import Response

from app.db import get_pool
from app.schemas import DocumentOut
from app.services.rag import delete_document_by_id

router = APIRouter(tags=["documents"])


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    pool: asyncpg.Pool | None = Depends(get_pool),
) -> list[DocumentOut]:
    if pool is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured (set SUPABASE_DB_URL)",
        )
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, filename, sha256, pages, char_count, created_at
            FROM documents
            ORDER BY created_at DESC
            """
        )
    return [DocumentOut(**dict(r)) for r in rows]


@router.get(
    "/documents/{doc_id}/page/{page_num}",
    response_class=HTMLResponse,
    name="document_page_view",
)
async def get_document_page(
    doc_id: UUID,
    page_num: int,
    pool: asyncpg.Pool | None = Depends(get_pool),
) -> HTMLResponse:
    """Plain HTML view of one PDF page's extracted text (citation target for handbooks)."""
    if pool is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured (set SUPABASE_DB_URL)",
        )
    if page_num < 1:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="page_num must be >= 1",
        )
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT filename, pages, page_texts
            FROM documents
            WHERE id = $1
            """,
            doc_id,
        )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found")
    texts = row["page_texts"]
    if not texts:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="No per-page text for this document (re-upload the PDF to enable citations).",
        )
    if not isinstance(texts, list) or page_num > len(texts):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Page not found")
    body = texts[page_num - 1]
    if not isinstance(body, str):
        body = str(body)
    fname = html.escape(row["filename"] or "document")
    total = int(row["pages"] or len(texts))
    prev_url = f"/documents/{doc_id}/page/{page_num - 1}" if page_num > 1 else None
    next_url = f"/documents/{doc_id}/page/{page_num + 1}" if page_num < total else None
    nav_parts: list[str] = []
    if prev_url:
        nav_parts.append(f'<a href="{prev_url}">← Previous</a>')
    if next_url:
        nav_parts.append(f'<a href="{next_url}">Next →</a>')
    nav = " · ".join(nav_parts) if nav_parts else ""
    safe_body = html.escape(body) if body else "<em>(empty page)</em>"
    html_page = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{fname} — page {page_num}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 1.25rem; max-width: 52rem; color: #0f172a; background: #f8fafc; }}
pre {{ white-space: pre-wrap; word-break: break-word; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 1rem; }}
nav {{ margin-bottom: 1rem; font-size: 0.9rem; }}
a {{ color: #0369a1; }}
</style></head><body>
<nav>{nav}</nav>
<h1>{fname}</h1>
<p>Page <strong>{page_num}</strong> of {total}</p>
<pre>{safe_body}</pre>
</body></html>"""
    return HTMLResponse(html_page)


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_document(
    doc_id: UUID,
    pool: asyncpg.Pool | None = Depends(get_pool),
) -> Response:
    if pool is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured (set SUPABASE_DB_URL)",
        )
    sid = str(doc_id)
    async with pool.acquire() as conn:
        deleted = await conn.execute(
            "DELETE FROM documents WHERE id = $1",
            doc_id,
        )
    if deleted == "DELETE 0":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found")
    await delete_document_by_id(sid)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
