"""Profile routes — GET /v1/profiles/{entity_id}, config CRUD."""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from emerald.api.dependencies import api_key_auth, rate_limit
from emerald.api.schemas.profiles import ProfileConfig as ProfileConfigSchema
from emerald.core.profile import ProfileConfig, ProfileManager

router = APIRouter(tags=["Profiles"])


def _get_engine(request: Request):
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Memory engine not configured")
    return engine


@router.get("/profiles/{entity_id}", dependencies=[Depends(api_key_auth), Depends(rate_limit)])
async def get_profile(entity_id: str, request: Request) -> dict:
    """Get entity profile (static + dynamic facts)."""
    start = time.perf_counter()
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
        "meta": {
            "request_id": request_id,
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


@router.get("/profiles/{entity_id}/config", dependencies=[Depends(api_key_auth), Depends(rate_limit)])
async def get_profile_config(entity_id: str, request: Request) -> dict:
    """Get per-entity profile configuration overrides."""
    start = time.perf_counter()
    engine = _get_engine(request)
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    manager = ProfileManager(graph=engine.graph)
    config = await manager.get_config(entity_id)

    return {
        "data": {
            "entity_id": entity_id,
            "config": {
                "static_max_items": config.static_max_items,
                "dynamic_max_items": config.dynamic_max_items,
                "dynamic_lookback_days": config.dynamic_lookback_days,
                "min_confidence_static": config.min_confidence_static,
                "min_confidence_dynamic": config.min_confidence_dynamic,
            },
        },
        "meta": {
            "request_id": request_id,
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


@router.put("/profiles/{entity_id}/config", dependencies=[Depends(api_key_auth), Depends(rate_limit)])
async def update_profile_config(
    entity_id: str,
    body: ProfileConfigSchema,
    request: Request,
) -> dict:
    """Set per-entity profile configuration overrides.

    Overrides are stored in Redis and take effect on the next profile
    computation.  The cached profile is invalidated immediately so the
    next GET returns a profile computed with the new config.
    """
    start = time.perf_counter()
    engine = _get_engine(request)
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    config = ProfileConfig(
        static_max_items=body.static_max_items,
        dynamic_max_items=body.dynamic_max_items,
        dynamic_lookback_days=body.dynamic_lookback_days,
        min_confidence_static=body.min_confidence_static,
        min_confidence_dynamic=body.min_confidence_dynamic,
    )

    manager = ProfileManager(graph=engine.graph)
    await manager.set_config(entity_id, config)

    return {
        "data": {
            "entity_id": entity_id,
            "config": {
                "static_max_items": config.static_max_items,
                "dynamic_max_items": config.dynamic_max_items,
                "dynamic_lookback_days": config.dynamic_lookback_days,
                "min_confidence_static": config.min_confidence_static,
                "min_confidence_dynamic": config.min_confidence_dynamic,
            },
        },
        "meta": {
            "request_id": request_id,
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


@router.delete("/profiles/{entity_id}/config", dependencies=[Depends(api_key_auth), Depends(rate_limit)])
async def delete_profile_config(entity_id: str, request: Request) -> dict:
    """Reset profile config to class defaults."""
    start = time.perf_counter()
    engine = _get_engine(request)
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    manager = ProfileManager(graph=engine.graph)
    deleted = await manager.delete_config(entity_id)

    return {
        "data": {
            "entity_id": entity_id,
            "deleted": deleted,
            "message": "Config reset to defaults" if deleted else "No config override exists",
        },
        "meta": {
            "request_id": request_id,
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }
