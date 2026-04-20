"""Pydantic API models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

_CHAT_ROLES = frozenset({"user", "assistant", "system"})


class UploadResultItem(BaseModel):
    id: UUID
    filename: str
    pages: int = Field(ge=0)
    char_count: int = Field(ge=0)
    status: Literal["ingested", "duplicate"]


class DocumentOut(BaseModel):
    id: UUID
    filename: str
    sha256: str
    pages: int = Field(ge=0)
    char_count: int = Field(ge=0)
    created_at: datetime


class ChatMessage(BaseModel):
    role: str
    content: str

    @field_validator("role")
    @classmethod
    def _role_ok(cls, v: str) -> str:
        if v not in _CHAT_ROLES:
            raise ValueError(f"role must be one of {sorted(_CHAT_ROLES)}")
        return v


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=32000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=50)
