"""Pipeline status routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from emerald.api.dependencies import api_key_auth
from emerald.db.session import session_factory
from emerald.models.pipeline_job import PipelineJob

router = APIRouter(tags=["Pipelines"])


@router.get("/pipelines/{pipeline_id}")
async def get_pipeline_status(
    pipeline_id: str,
    _: str = Depends(api_key_auth),
) -> dict:
    from sqlalchemy import select

    async with session_factory.session() as session:
        result = await session.execute(
            select(PipelineJob).where(PipelineJob.id == pipeline_id)
        )
        job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(404, f"Pipeline {pipeline_id} not found")

    return {
        "data": {
            "pipeline_id": str(job.id),
            "status": job.status,
            "entity_id": str(job.entity_id),
            "document_id": str(job.document_id) if job.document_id else None,
            "content_type": getattr(job, "content_type", None),
            "error_message": job.error_message,
            "retry_count": job.retry_count,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }
    }
