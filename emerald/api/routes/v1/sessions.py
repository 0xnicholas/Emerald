"""Session routes — JWT session token issue/verify."""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from emerald.api.dependencies import api_key_auth, rate_limit
from emerald.core.session import SessionManager

router = APIRouter(tags=["Sessions"])


def _get_engine(request: Request):
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Memory engine not configured")
    return engine


@router.post(
    "/sessions",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(api_key_auth), Depends(rate_limit)],
)
async def create_session(
    request: Request,
    entity_id: str,
    project_id: str | None = None,
    session_id: str | None = None,
    ttl_hours: float = 24,
) -> dict:
    """Issue a short-lived JWT session token scoped to an entity/project."""
    start = time.perf_counter()
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    api_entity_id = getattr(request.state, "entity_id", None)
    if api_entity_id and api_entity_id != entity_id:
        raise HTTPException(
            status_code=403,
            detail="Cannot issue session token for a different entity",
        )

    manager = SessionManager()
    token = manager.create_token(
        entity_id=entity_id,
        project_id=project_id,
        session_id=session_id,
        ttl_hours=ttl_hours,
    )

    return {
        "data": {
            "token": token,
            "entity_id": entity_id,
            "project_id": project_id,
            "session_id": session_id,
            "expires_in_hours": ttl_hours,
        },
        "meta": {
            "request_id": request_id,
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


@router.get(
    "/sessions/verify",
    dependencies=[Depends(api_key_auth), Depends(rate_limit)],
)
async def verify_session(
    request: Request,
    x_session_token: str = Header(..., alias="X-Session-Token"),
) -> dict:
    """Verify a session token and return its claims."""
    start = time.perf_counter()
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    manager = SessionManager()
    try:
        claims = manager.decode_token(x_session_token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    api_entity_id = getattr(request.state, "entity_id", None)
    if api_entity_id and claims.get("entity_id") != api_entity_id:
        raise HTTPException(
            status_code=403,
            detail="Session token entity does not match API key entity",
        )

    return {
        "data": {
            "valid": True,
            "claims": claims,
        },
        "meta": {
            "request_id": request_id,
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }
