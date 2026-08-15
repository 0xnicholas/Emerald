"""Pipeline status routes."""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException

from emerald.api.dependencies import api_key_auth
from emerald.api.schemas.pipeline import PipelineStatusEnvelope, PipelineStatusResponse
from emerald.db.session import session_factory
from emerald.models.pipeline_job import PipelineJob

router = APIRouter(tags=["Pipelines"])


@router.get(
    "/pipelines/{pipeline_id}",
    response_model=PipelineStatusEnvelope,
)
async def get_pipeline_status(
    pipeline_id: str,
    _: str = Depends(api_key_auth),
) -> dict:
    """Look up the current status of an async pipeline job (file upload,
    large-document extraction, embedding indexing).

    Status values: queued | extracting | chunking | embedding | indexing | done | failed.
    """
    start = time.perf_counter()
    from sqlalchemy import select

    async with session_factory.session() as session:
        result = await session.execute(
            select(PipelineJob).where(PipelineJob.id == pipeline_id)
        )
        job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(404, f"Pipeline {pipeline_id} not found")

    payload = PipelineStatusResponse(
        pipeline_id=str(job.id),
        status=job.status,
        document_id=str(job.document_id) if job.document_id else None,
        content_type=job.content_type or "",
        error_message=job.error_message,
        fact_extraction_status=getattr(job, "fact_extraction_status", None),
        memory_count=getattr(job, "memory_count", 0),
    )
    return {
        "data": payload.model_dump(),
        "meta": {
            "request_id": str(uuid.uuid4())[:8],
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }
