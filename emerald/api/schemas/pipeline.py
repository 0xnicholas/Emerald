"""Pipeline status schema."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PipelineStatusResponse(BaseModel):
    pipeline_id: str
    status: str  # queued | extracting | chunking | embedding | indexing | done | failed
    stage: str = ""
    document_id: str | None = None
    content_type: str = ""
    chunk_count: int = 0
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
