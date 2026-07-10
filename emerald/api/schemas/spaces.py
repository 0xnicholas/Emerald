"""Space API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SpaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100, examples=["Work"])
    emoji: str = Field(default="📁", max_length=10, examples=["💼"])
    entity_id: str = Field(examples=["user_123"])


class SpaceUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    emoji: str | None = Field(default=None, max_length=10)


class SpaceResponse(BaseModel):
    container_tag: str
    name: str
    emoji: str
    entity_id: str
    memory_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
