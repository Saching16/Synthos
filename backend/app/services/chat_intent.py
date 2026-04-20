"""Handbook vs normal chat intent (Phase 7)."""

from __future__ import annotations

import re

_HANDBOOK = re.compile(
    r"handbook|long-form|20[\s,]?000\s*words?|comprehensive\s+guide",
    re.IGNORECASE,
)
_TOPIC = re.compile(
    r"\b(?:about|on)\s+(.+?)(?:\.|$)",
    re.IGNORECASE | re.DOTALL,
)


def is_handbook_request(message: str) -> bool:
    """True when the user is asking for the long-form handbook flow."""
    return bool(message and _HANDBOOK.search(message))


def extract_handbook_topic(message: str) -> str:
    """Best-effort topic string for ``/handbook`` (subtitle after *about* / *on*)."""
    t = (message or "").strip()
    m = _TOPIC.search(t)
    if m:
        return m.group(1).strip().strip('"').strip("'")[:500]
    return t[:500]
