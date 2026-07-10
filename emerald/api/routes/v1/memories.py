"""Memory routes — POST/GET/DELETE /v1/memories."""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status

from emerald.api.dependencies import (
    api_key_auth,
    authorize_entity,
    rate_limit,
    require_write_permission,
)
from emerald.api.schemas import AddMemoryRequest, BatchAddMemoryRequest, MemoryResponse, UpdateMemoryRequest

router = APIRouter(tags=["Memories"])


def _get_engine(request: Request):
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="Memory engine not configured",
        )
    return engine


# Local alias preserves the existing call-site signature (N5 refactor).
_authorize_entity = authorize_entity


async def _get_authorized_memory(engine, request: Request, memory_id: str) -> dict:
    """Fetch a memory and verify it belongs to the API key's entity."""
    memory = await engine.graph.get_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    _authorize_entity(request, memory.get("entity_id", ""))
    return memory


@router.post(
    "/memories",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(api_key_auth), Depends(require_write_permission), Depends(rate_limit)],
)
async def add_memory(body: AddMemoryRequest, request: Request) -> dict:
    """Add content to the memory graph."""
    start = time.perf_counter()
    _authorize_entity(request, body.entity_id)
    engine = _get_engine(request)
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    result = await engine.add(
        content=body.content,
        entity_id=body.entity_id,
        content_type=body.content_type or "text",
        metadata=body.metadata,
        idempotency_key=body.idempotency_key,
        require_confirmation_for_high_impact=body.require_confirmation_for_high_impact,
        memory_type=body.memory_type,
        confidence=body.confidence,
        valid_until=body.valid_until,
        container_tag=body.container_tag,
    )

    return {
        "data": {
            "memory_ids": result.memory_ids,
            "pipeline_status": result.pipeline_status,
            "extracted_count": result.extracted_count,
            "conflicts_pending": result.conflicts_pending,
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
    memory = await _get_authorized_memory(engine, request, memory_id)
    safe = MemoryResponse(
        id=memory["id"],
        content=memory["content"],
        summary=memory.get("summary", ""),
        memory_type=memory.get("memory_type", "fact"),
        container_tag=memory.get("container_tag", "default"),
        is_latest=memory.get("is_latest", True),
        confidence=memory.get("confidence", 0.0),
        valid_from=memory.get("valid_from"),
        valid_until=memory.get("valid_until"),
        entity_id=memory.get("entity_id", ""),
        validation_count=memory.get("validation_count", 0),
        created_at=memory.get("created_at"),
        updated_at=memory.get("updated_at"),
    )
    return {
        "data": safe.model_dump(),
        "meta": {
            "request_id": getattr(request.state, "request_id", ""),
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


@router.post("/memories/{memory_id}/validate", dependencies=[Depends(api_key_auth)])
async def validate_memory(memory_id: str, request: Request) -> dict:
    """Increment a memory's validation_count (signals higher trust)."""
    start = time.perf_counter()
    engine = _get_engine(request)
    memory = await _get_authorized_memory(engine, request, memory_id)

    await engine.graph.validate_memory(memory_id)
    # Refresh profile so trust score changes are reflected
    await engine.profile_manager.invalidate(memory.get("entity_id", ""))

    return {
        "data": {"validated": True, "memory_id": memory_id},
        "meta": {
            "request_id": getattr(request.state, "request_id", ""),
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


@router.patch("/memories/{memory_id}", dependencies=[Depends(api_key_auth), Depends(require_write_permission), Depends(rate_limit)])
async def update_memory(memory_id: str, body: UpdateMemoryRequest, request: Request) -> dict:
    """Update a memory's content, summary, type, and/or confidence."""
    start = time.perf_counter()
    engine = _get_engine(request)
    memory = await _get_authorized_memory(engine, request, memory_id)

    update_kwargs = body.model_dump(exclude_none=True)
    if not update_kwargs:
        raise HTTPException(status_code=400, detail="No fields to update")

    await engine.graph.update_memory(memory_id, **update_kwargs)
    # Refresh profile so changes are reflected
    await engine.profile_manager.invalidate(memory.get("entity_id", ""))

    return {
        "data": {"updated": True, "memory_id": memory_id},
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
    await _get_authorized_memory(engine, request, memory_id)

    await engine.graph.update_is_latest(memory_id, False)
    return {
        "data": {"deleted": True, "memory_id": memory_id},
        "meta": {
            "request_id": getattr(request.state, "request_id", ""),
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


@router.post(
    "/memories/batch",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(api_key_auth), Depends(require_write_permission), Depends(rate_limit)],
)
async def add_memories_batch(body: BatchAddMemoryRequest, request: Request) -> dict:
    """Add multiple memories in a single request (up to 50)."""
    start = time.perf_counter()
    engine = _get_engine(request)
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    # Authorize all target entities up front
    for mem in body.memories:
        _authorize_entity(request, mem.entity_id)

    results = []
    for mem in body.memories:
        try:
            result = await engine.add(
                content=mem.content,
                entity_id=mem.entity_id,
                content_type=mem.content_type or "text",
                metadata=mem.metadata,
                idempotency_key=mem.idempotency_key,
                require_confirmation_for_high_impact=mem.require_confirmation_for_high_impact,
                memory_type=mem.memory_type,
                confidence=mem.confidence,
                valid_until=mem.valid_until,
            )
            results.append({
                "memory_ids": result.memory_ids,
                "pipeline_status": result.pipeline_status,
                "extracted_count": result.extracted_count,
                "conflicts_pending": result.conflicts_pending,
            })
        except Exception as exc:
            results.append({
                "memory_ids": [],
                "pipeline_status": "error",
                "extracted_count": 0,
                "error": str(exc),
            })

    succeeded = sum(1 for r in results if r.get("pipeline_status") == "done")

    return {
        "data": {
            "results": results,
            "succeeded": succeeded,
            "failed": len(results) - succeeded,
        },
        "meta": {
            "request_id": request_id,
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }
