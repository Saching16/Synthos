"""GET /documents and DELETE /documents/{id}."""

from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
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
