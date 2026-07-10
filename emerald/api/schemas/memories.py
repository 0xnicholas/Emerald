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
        description=(
            "Client-provided idempotency key. "
            "Same key + entity yields same result for 1 hour."
        ),
    )
    require_confirmation_for_high_impact: bool = Field(
        default=False,
        description=(
            "When true, high-impact contradictions are flagged for confirmation "
            "instead of auto-resolved."
        ),
    )
    # ---- Per-memory overrides (P1.2a) ----
    # Callers who know better than the LLM extractor (e.g. an onboarding
    # flow that has just collected a structured preference) can set these
    # directly.  When set, they take precedence over both the chunker's
    # default and any value tucked into ``metadata``.
    memory_type: str | None = Field(
        default=None,
        description=(
            "Override the LLM-extracted memory type. Must be one of "
            "'fact', 'preference', or 'episodic' if provided."
        ),
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Override the LLM-assigned confidence score (0.0-1.0). "
            "Useful for human-verified or operator-curated entries."
        ),
    )
    container_tag: str | None = Field(
        default=None,
        description=(
            "Optional space/container tag to associate this memory with. "
            "Default is 'default' (My Space)."
        ),
    )
    valid_until: datetime | None = Field(
        default=None,
        description=(
            "When this memory should be considered expired (e.g. "
            "'I have an exam tomorrow'). The ForgetEngine will mark it "
            "not_latest after this time. None means no expiry."
        ),
    )


class AddMemoryResponse(BaseModel):
    memory_ids: list[str]
    pipeline_status: str = "done"
    extracted_count: int = 0
    conflicts_pending: list[dict] = Field(default_factory=list)


class RelationshipItem(BaseModel):
    type: str  # updates | extends | derives_from
    target_id: str
    target_summary: str


class MemoryResponse(BaseModel):
    id: str
    content: str
    summary: str = ""
    memory_type: str = "fact"
    container_tag: str = "default"
    is_latest: bool = True
    confidence: float = 0.0
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    entity_id: str
    validation_count: int = 0
    relationships: list[RelationshipItem] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class UpdateMemoryRequest(BaseModel):
    content: str | None = Field(default=None, examples=["Updated content"])
    summary: str | None = Field(default=None, examples=["Updated summary"])
    memory_type: str | None = Field(default=None, pattern=r"^(fact|preference|episodic)$")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class BatchAddMemoryRequest(BaseModel):
    memories: list[AddMemoryRequest] = Field(
        max_length=50,
        description="Up to 50 memories to add in a single batch.",
    )


class BatchAddMemoryResponse(BaseModel):
    results: list[AddMemoryResponse]
    succeeded: int = 0
    failed: int = 0
