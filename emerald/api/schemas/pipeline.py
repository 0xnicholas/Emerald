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
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    # P1.2b: surface fact-extraction + memory count in the public schema
    fact_extraction_status: str | None = None  # success | failed | skipped
    memory_count: int = 0
    # NOTE: ``chunk_count`` was removed because the pipeline_jobs table
    # doesn't track it.  If/when chunk counting is added, reintroduce the
    # field here AND in PipelineStatus dataclass in the same commit.


class PipelineStatusEnvelope(BaseModel):
    """Envelope for GET /v1/pipelines/{id}（与 keys.py 的 Envelope 派惯例一致）。

    此前路由声明 response_model=PipelineStatusResponse 但返回 {data, meta}
    信封，导致每次命中都 ResponseValidationError→500（D2 轮询依赖端点，
    2026-08-15 :80 冒烟发现）。"""

    data: PipelineStatusResponse
    meta: dict
