"""Memory routes — POST/GET/DELETE /v1/memories."""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status

from emerald.api.dependencies import api_key_auth, rate_limit, require_write_permission
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
    dependencies=[Depends(api_key_auth), Depends(require_write_permission), Depends(rate_limit)],
)
async def add_memory(body: AddMemoryRequest, request: Request) -> dict:
    """Add content to the memory graph."""
    start = time.perf_counter()
    engine = _get_engine(request)
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    result = await engine.add(
        content=body.content,
        entity_id=body.entity_id,
        content_type=body.content_type or "text",
        metadata=body.metadata,
        idempotency_key=body.idempotency_key,
    )

    return {
        "data": {
            "memory_ids": result.memory_ids,
            "pipeline_status": result.pipeline_status,
            "extracted_count": result.extracted_count,
        },
        "meta": {
            "request_id": request_id,
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


@router.get("/memories/{memory_id}", dependencies=[Depends(api_key_auth)])
async def get_memory(memory_id: str, request: Request) -> dict:
    """Get a single memory by ID."""
    start = time.perf_counter()
    engine = _get_engine(request)
    memory = await engine.graph.get_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {
        "data": memory,
        "meta": {
            "request_id": getattr(request.state, "request_id", ""),
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


@router.delete("/memories/{memory_id}", dependencies=[Depends(api_key_auth)])
async def delete_memory(memory_id: str, request: Request) -> dict:
    """Delete a memory by ID (soft delete — mark as not latest)."""
    start = time.perf_counter()
    engine = _get_engine(request)
    memory = await engine.graph.get_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    await engine.graph.update_is_latest(memory_id, False)
    return {
        "data": {"deleted": True, "memory_id": memory_id},
        "meta": {
            "request_id": getattr(request.state, "request_id", ""),
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }
