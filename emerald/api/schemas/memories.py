"""Memory API schemas — request/response models for /v1/memories."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AddMemoryRequest(BaseModel):
    content: str = Field(examples=["用户偏好 TypeScript 和函数式编程风格"])
    entity_id: str = Field(examples=["user_123"])
    content_type: str | None = Field(default=None, examples=["text"])
    title: str | None = None
    metadata: dict | None = None
    async_mode: bool = False
    idempotency_key: str | None = Field(
        default=None,
        description="Client-provided idempotency key. Same key + entity yields same result for 1 hour.",
    )


class AddMemoryResponse(BaseModel):
    memory_ids: list[str]
    pipeline_status: str = "done"
    extracted_count: int = 0


class RelationshipItem(BaseModel):
    type: str  # updates | extends | derives_from
    target_id: str
    target_summary: str


class MemoryResponse(BaseModel):
    id: str
    content: str
    summary: str = ""
    memory_type: str = "fact"
    is_latest: bool = True
    confidence: float = 0.0
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    entity_id: str
    relationships: list[RelationshipItem] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
