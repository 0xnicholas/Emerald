"""Memory routes — POST/GET/DELETE /v1/memories."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status

from emerald.api.dependencies import rate_limit
from emerald.api.schemas import AddMemoryRequest

router = APIRouter(tags=["Memories"])


def _get_engine(request: Request):
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="Memory engine not configured",
        )
    return engine


@router.post(
    "/memories",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(rate_limit)],
)
async def add_memory(body: AddMemoryRequest, request: Request) -> dict:
    """Add content to the memory graph."""
    engine = _get_engine(request)
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    result = await engine.add(
        content=body.content,
        entity_id=body.entity_id,
        content_type=body.content_type or "text",
        metadata=body.metadata,
    )

    return {
        "data": {
            "memory_ids": result.memory_ids,
            "pipeline_status": result.pipeline_status,
            "extracted_count": result.extracted_count,
        },
        "meta": {"request_id": request_id},
    }


@router.get("/memories/{memory_id}")
async def get_memory(memory_id: str, request: Request) -> dict:
    """Get a single memory by ID."""
    engine = _get_engine(request)
    memory = await engine.graph.get_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {
        "data": memory,
        "meta": {"request_id": getattr(request.state, "request_id", "")},
    }
