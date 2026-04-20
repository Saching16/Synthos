"""Pydantic API models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


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
