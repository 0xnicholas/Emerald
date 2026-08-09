"""Space routes — CRUD /v1/spaces."""

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
from emerald.api.schemas import SpaceCreateRequest, SpaceResponse, SpaceUpdateRequest

router = APIRouter(tags=["Spaces"])


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


@router.get(
    "/spaces",
    dependencies=[Depends(api_key_auth)],
)
async def list_spaces(entity_id: str, request: Request) -> dict:
    """List all spaces for an entity."""
    start = time.perf_counter()
    _authorize_entity(request, entity_id)
    engine = _get_engine(request)
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    spaces = await engine.graph.list_spaces(entity_id)

    return {
        "data": [SpaceResponse(**s).model_dump() for s in spaces],
        "meta": {
            "request_id": request_id,
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


@router.post(
    "/spaces",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(api_key_auth), Depends(require_write_permission), Depends(rate_limit)],
)
async def create_space(body: SpaceCreateRequest, request: Request) -> dict:
    """Create a new space."""
    start = time.perf_counter()
    _authorize_entity(request, body.entity_id)
    engine = _get_engine(request)
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    container_tag = body.name.lower().replace(" ", "-")
    space = await engine.graph.create_space(
        container_tag=container_tag,
        name=body.name,
        emoji=body.emoji,
        entity_id=body.entity_id,
    )

    return {
        "data": SpaceResponse(**space).model_dump(),
        "meta": {
            "request_id": request_id,
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


@router.patch(
    "/spaces/{container_tag}",
    dependencies=[Depends(api_key_auth), Depends(require_write_permission), Depends(rate_limit)],
)
async def update_space(container_tag: str, entity_id: str, body: SpaceUpdateRequest, request: Request) -> dict:
    """Update a space's name and/or emoji."""
    start = time.perf_counter()
    _authorize_entity(request, entity_id)
    engine = _get_engine(request)
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    try:
        space = await engine.graph.update_space(
            container_tag=container_tag,
            entity_id=entity_id,
            name=body.name,
            emoji=body.emoji,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Space not found")

    return {
        "data": SpaceResponse(**space).model_dump(),
        "meta": {
            "request_id": request_id,
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


@router.delete(
    "/spaces/{container_tag}",
    dependencies=[Depends(api_key_auth), Depends(require_write_permission), Depends(rate_limit)],
)
async def delete_space(
    container_tag: str,
    entity_id: str,
    detach_memories: bool = True,
    request: Request = None,
) -> dict:
    """Delete a space. Memories are detached (container_tag becomes null) by default."""
    start = time.perf_counter()
    _authorize_entity(request, entity_id)
    engine = _get_engine(request)
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    await engine.graph.delete_space(
        container_tag=container_tag,
        entity_id=entity_id,
        detach_memories=detach_memories,
    )

    return {
        "data": {"deleted": True, "container_tag": container_tag, "entity_id": entity_id},
        "meta": {
            "request_id": request_id,
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }
