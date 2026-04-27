"""POST /upload — PDF bytes to ``documents`` + LightRAG."""

from __future__ import annotations

import logging

import asyncpg
from asyncpg.exceptions import UndefinedColumnError
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.db import get_pool
from app.schemas import UploadResultItem
from app.services.pdf import extract_text, sha256_hex
from app.services.rag import insert_document

logger = logging.getLogger(__name__)

router = APIRouter(tags=["upload"])


def _is_pdf(filename: str | None, content_type: str | None) -> bool:
    if (filename or "").lower().endswith(".pdf"):
        return True
    ct = (content_type or "").lower().split(";", 1)[0].strip()
    return ct in ("application/pdf", "application/x-pdf")


@router.post("/upload", response_model=list[UploadResultItem])
async def upload_pdfs(
    files: list[UploadFile] = File(
        ...,
        description="One or more PDF files (multipart name: files)",
    ),
    pool: asyncpg.Pool | None = Depends(get_pool),
) -> list[UploadResultItem]:
    if pool is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured (set SUPABASE_DB_URL)",
        )
    if not files:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="No files uploaded",
        )

    out: list[UploadResultItem] = []
    for uf in files:
        name = uf.filename or "document.pdf"
        if not _is_pdf(uf.filename, uf.content_type):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Not a PDF: {name}",
            )
        raw = await uf.read()
        if not raw:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Empty file: {name}",
            )

        digest = sha256_hex(raw)
        try:
            extracted = extract_text(raw)
        except Exception as e:
            logger.exception("PDF extract failed for %s", name)
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Could not read PDF: {name}",
            ) from e

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, filename, pages, char_count
                FROM documents
                WHERE sha256 = $1
                """,
                digest,
            )
        if row:
            out.append(
                UploadResultItem(
                    id=row["id"],
                    filename=row["filename"],
                    pages=row["pages"],
                    char_count=row["char_count"],
                    status="duplicate",
                )
            )
            continue

        async with pool.acquire() as conn:
            try:
                ins = await conn.fetchrow(
                    """
                    INSERT INTO documents (filename, sha256, pages, char_count, page_texts)
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING id, filename, pages, char_count
                    """,
                    name,
                    digest,
                    extracted.pages,
                    extracted.char_count,
                    extracted.page_texts,
                )
            except UndefinedColumnError:
                logger.warning(
                    "documents.page_texts missing — run supabase/schema.sql (ALTER). "
                    "Ingesting without per-page storage (citation viewer disabled until migrated)."
                )
                ins = await conn.fetchrow(
                    """
                    INSERT INTO documents (filename, sha256, pages, char_count)
                    VALUES ($1, $2, $3, $4)
                    RETURNING id, filename, pages, char_count
                    """,
                    name,
                    digest,
                    extracted.pages,
                    extracted.char_count,
                )
        assert ins is not None
        doc_id_str = str(ins["id"])
        try:
            await insert_document(extracted.text, doc_id_str)
        except Exception:
            logger.exception(
                "LightRAG ingest failed for %s doc_id=%s", name, doc_id_str
            )
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM documents WHERE id = $1", ins["id"])
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to index document: {name}",
            ) from None

        out.append(
            UploadResultItem(
                id=ins["id"],
                filename=ins["filename"],
                pages=ins["pages"],
                char_count=ins["char_count"],
                status="ingested",
            )
        )
    return out
