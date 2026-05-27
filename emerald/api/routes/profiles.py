"""Profile routes — GET /v1/profiles/{entity_id}."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from emerald.api.dependencies import api_key_auth, rate_limit
from emerald.core.profile import ProfileManager

router = APIRouter(tags=["Profiles"])


def _get_engine(request: Request):
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Memory engine not configured")
    return engine


@router.get("/profiles/{entity_id}", dependencies=[Depends(api_key_auth), Depends(rate_limit)])
async def get_profile(entity_id: str, request: Request) -> dict:
    """Get entity profile (static + dynamic facts)."""
    engine = _get_engine(request)
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    manager = ProfileManager(graph=engine.graph)
    profile = await manager.get(entity_id)

    return {
        "data": {
            "entity_id": profile.entity_id,
            "static": [
                {"content": f.content, "importance": f.importance}
                for f in profile.static
            ],
            "dynamic": [
                {"content": f.content, "relevance": f.relevance, "source": f.source}
                for f in profile.dynamic
            ],
            "memory_count": profile.memory_count,
            "computed_at": profile.computed_at,
            "version": profile.version,
        },
        "meta": {"request_id": request_id},
    }
