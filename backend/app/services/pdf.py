"""PDF text extraction: pypdf first, pdfplumber fallback, repeated line stripping, hashing."""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections import defaultdict
from io import BytesIO
from pathlib import Path

import pdfplumber
from pydantic import BaseModel, Field
from pypdf import PdfReader

CHAR_FALLBACK_THRESHOLD = 30


class ExtractedDoc(BaseModel):
    """``text`` is what LightRAG ingests (includes ``<<PAGE n>>`` markers)."""

    text: str
    page_texts: list[str]
    pages: int = Field(ge=0)
    char_count: int = Field(ge=0)


def sha256_hex(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def _normalize_line(line: str) -> str:
    return " ".join(line.split())


def _pypdf_page_text(reader: PdfReader, page_index: int) -> str:
    return reader.pages[page_index].extract_text() or ""


def _extract_page_texts(file_bytes: bytes) -> tuple[list[str], int]:
    reader = PdfReader(BytesIO(file_bytes))
    n = len(reader.pages)
    texts = [_pypdf_page_text(reader, i) for i in range(n)]
    low_idx = [
        i for i, t in enumerate(texts) if len(t.strip()) < CHAR_FALLBACK_THRESHOLD
    ]
    if low_idx:
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            for i in low_idx:
                alt = pdf.pages[i].extract_text() or ""
                if len(alt.strip()) > len(texts[i].strip()):
                    texts[i] = alt
    return texts, n


def _repeated_line_norms(page_texts: list[str], page_fraction: float = 0.5) -> set[str]:
    n_pages = len(page_texts)
    if n_pages < 2:
        return set()
    norm_to_pages: dict[str, set[int]] = defaultdict(set)
    for pi, page in enumerate(page_texts):
        seen_on_page: set[str] = set()
        for line in page.splitlines():
            norm = _normalize_line(line)
            if not norm:
                continue
            if norm in seen_on_page:
                continue
            seen_on_page.add(norm)
            norm_to_pages[norm].add(pi)
    cutoff = page_fraction * n_pages
    return {norm for norm, pages in norm_to_pages.items() if len(pages) > cutoff}


def _strip_lines(page_text: str, strip_norms: set[str]) -> str:
    out: list[str] = []
    for line in page_text.splitlines():
        norm = _normalize_line(line)
        if norm and norm in strip_norms:
            continue
        out.append(line)
    return "\n".join(out)


def extract_text(file_bytes: bytes) -> ExtractedDoc:
    page_texts, pages = _extract_page_texts(file_bytes)
    strip_norms = _repeated_line_norms(page_texts)
    cleaned_pages = [_strip_lines(p, strip_norms) for p in page_texts]
    stored_pages = [p.strip() for p in cleaned_pages]
    blocks: list[str] = []
    for i, page in enumerate(stored_pages, start=1):
        blocks.append(f"<<PAGE {i}>>\n{page}")
    full = "\n\n".join(blocks).strip()
    plain = "\n\n".join(p for p in stored_pages if p).strip()
    return ExtractedDoc(
        text=full,
        page_texts=stored_pages,
        pages=pages,
        char_count=len(plain) if plain else 0,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract text from a PDF (smoke test)."
    )
    parser.add_argument("path", type=Path, help="Path to a .pdf file")
    args = parser.parse_args()
    file_bytes = args.path.read_bytes()
    doc = extract_text(file_bytes)
    digest = sha256_hex(file_bytes)
    sample_len = 4000
    sample = doc.text[:sample_len]
    sys.stdout.write(
        f"pages={doc.pages} char_count={doc.char_count} sha256={digest}\n---\n{sample}"
    )
    if len(doc.text) > sample_len:
        sys.stdout.write("\n---\n... [truncated]\n")


if __name__ == "__main__":
    main()
