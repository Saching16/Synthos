"""On-disk cache for AgentWrite LLM calls (stretch: cut repeat API cost)."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)


def _root() -> Path | None:
    s = get_settings()
    if not s.agentwrite_cache_enabled:
        return None
    return s.handbooks_path / ".agentwrite_cache"


def _key_hex(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x1e")
    return h.hexdigest()


def try_read(kind: str, *key_parts: str) -> str | None:
    root = _root()
    if root is None:
        return None
    path = root / kind / f"{_key_hex(*key_parts)}.txt"
    if not path.is_file():
        return None
    logger.debug("agentwrite_llm_cache hit kind=%s path=%s", kind, path.name)
    return path.read_text(encoding="utf-8")


def store(kind: str, text: str, *key_parts: str) -> None:
    root = _root()
    if root is None:
        return
    path = root / kind / f"{_key_hex(*key_parts)}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
