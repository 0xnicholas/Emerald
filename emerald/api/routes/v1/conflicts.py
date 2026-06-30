"""Conflict resolution routes — POST /v1/conflicts/{id}/resolve."""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from emerald.api.dependencies import (
    api_key_auth,
    authorize_entity,
    require_write_permission,
)
from emerald.core.conflict import ConflictEngine, ResolutionAction

router = APIRouter(tags=["Conflicts"])


class ResolveConflictRequest(BaseModel):
    action: ResolutionAction


def _get_engine(request: Request):
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="Memory engine not configured",
        )
    return engine


# Local alias (N5 refactor: helper centralised in api.dependencies).
_authorize_entity = authorize_entity


@router.post(
    "/conflicts/{conflict_id}/resolve",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(api_key_auth), Depends(require_write_permission)],
)
async def resolve_conflict(
    conflict_id: str,
    body: ResolveConflictRequest,
    request: Request,
) -> dict:
    """Resolve a pending high-impact conflict."""
    start = time.perf_counter()
    engine = _get_engine(request)
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    action = body.action

    conflict_engine = ConflictEngine(graph=engine.graph)
    rel = await engine.graph.get_relationship_by_property(
        rel_type="PENDING_CONFLICT", key="conflict_id", value=conflict_id
    )
    if not rel:
        raise HTTPException(status_code=404, detail="Conflict not found")

    memory = await engine.graph.get_memory(rel["from_id"])
    if not memory:
        raise HTTPException(status_code=404, detail="Conflict memory not found")
    _authorize_entity(request, memory.get("entity_id", ""))

    try:
        result = await conflict_engine.resolve(conflict_id, action)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "data": result,
        "meta": {
            "request_id": request_id,
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }
