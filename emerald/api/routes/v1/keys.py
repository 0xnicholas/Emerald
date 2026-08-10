"""API key management routes (issue #5) — admin-only, entity-scoped.

Replaces ``scripts/seed_dev_api_key.py`` as the production onboarding
path (the seed script remains for local development only):

- ``POST   /v1/keys``          — create (admin): plaintext key returned once
- ``GET    /v1/keys``          — list (admin): metadata, cursor pagination
- ``DELETE /v1/keys/{key_id}`` — revoke (admin): key immediately invalid (401)

Security properties (AGENTS.md #7): the management surface lives in REST
only (no SDK methods); every operation requires the ``admin`` permission;
entity scope is enforced by comparing the target entity's internal UUID
with the caller's (``authorize_entity``) — an admin key manages keys of
its own entity only.  The server stores only the SHA-256 hash of each key
plus its prefix; plaintext is returned once at creation and never stored.
Revocation is a soft delete (``is_active=False``): the auth query already
filters ``is_active=True``, so a revoked key is rejected with 401 on the
next request.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from emerald.api.dependencies import (
    api_key_auth,
    authorize_entity,
    rate_limit,
    require_admin_permission,
)
from emerald.db.session import session_factory

router = APIRouter(tags=["Keys"])

_authorize_entity = authorize_entity


@router.post(
    "/keys",
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(api_key_auth),
        Depends(require_admin_permission),
        Depends(rate_limit),
    ],
)
async def create_key(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """Create an API key for the caller's entity.  The plaintext key is
    returned exactly once; only its SHA-256 hash is stored."""
    from emerald.api.schemas.keys import ALLOWED_PERMISSIONS, CreateKeyRequest

    parsed = CreateKeyRequest.model_validate(body)
    if not parsed.permissions or not set(parsed.permissions) <= set(ALLOWED_PERMISSIONS):
        raise HTTPException(
            status_code=422,
            detail=f"permissions must be a non-empty subset of {list(ALLOWED_PERMISSIONS)}",
        )

    from sqlalchemy import select

    from emerald.models.api_key import ApiKey
    from emerald.models.entity import Entity

    start = time.perf_counter()
    async with session_factory.session() as session:
        entity_result = await session.execute(
            select(Entity).where(Entity.external_id == parsed.entity_id)
        )
        entity = entity_result.scalar_one_or_none()
        if not entity:
            raise HTTPException(
                status_code=404, detail=f"Entity not found: {parsed.entity_id}"
            )
        # Entity scope: the internal UUID comparison (authorize_entity with
        # external ids would never match — request.state.entity_id is the
        # internal UUID from the caller's ApiKey record).
        _authorize_entity(request, str(entity.id))

        raw_key = "em_" + secrets.token_urlsafe(24)
        record = ApiKey(
            entity_id=entity.id,
            key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
            key_prefix=raw_key[:8],
            permissions=sorted(set(parsed.permissions)),
            expires_at=parsed.expires_at,
            is_active=True,
        )
        session.add(record)
        await session.commit()

    return {
        "data": {
            "key": raw_key,
            "key_id": str(record.id),
            "key_prefix": raw_key[:8],
            "permissions": record.permissions,
            "expires_at": parsed.expires_at.isoformat() if parsed.expires_at else None,
            "entity_id": parsed.entity_id,
        },
        "meta": {
            "request_id": getattr(request.state, "request_id", str(uuid4())[:8]),
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


@router.get(
    "/keys",
    dependencies=[
        Depends(api_key_auth),
        Depends(require_admin_permission),
        Depends(rate_limit),
    ],
)
async def list_keys(
    request: Request,
    page_token: str | None = Query(None, description="Cursor token for pagination"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
) -> dict[str, Any]:
    """List the caller's entity's key metadata (no hashes, no raw keys)."""
    from emerald.api.pagination import InvalidPaginationToken, PageToken

    try:
        token = PageToken.decode_or_raise(page_token, default_limit=page_size, max_limit=100)
    except InvalidPaginationToken as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    effective_limit = token.limit

    from sqlalchemy import select

    from emerald.models.api_key import ApiKey

    caller_entity = UUID(getattr(request.state, "entity_id", ""))
    start = time.perf_counter()

    async with session_factory.session() as session:
        query = (
            select(ApiKey)
            .where(ApiKey.entity_id == caller_entity)
            .order_by(ApiKey.created_at.desc(), ApiKey.id.desc())
            .limit(effective_limit + 1)
        )
        if token.cursor:
            query = query.where(ApiKey.id < token.cursor)

        keys = (await session.execute(query)).scalars().all()

    has_more = len(keys) > effective_limit
    if has_more:
        keys = keys[:effective_limit]

    next_token = None
    if has_more and keys:
        next_token = PageToken.encode(cursor=str(keys[-1].id), limit=effective_limit)

    items = [
        {
            "key_id": str(k.id),
            "key_prefix": k.key_prefix,
            "permissions": k.permissions,
            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "is_active": k.is_active,
            "created_at": k.created_at.isoformat() if k.created_at else None,
        }
        for k in keys
    ]

    return {
        "data": {"items": items, "page_size": effective_limit},
        "meta": {
            "request_id": getattr(request.state, "request_id", str(uuid4())[:8]),
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
        "pagination": {"next_page_token": next_token, "has_more": has_more},
    }


@router.delete(
    "/keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        Depends(api_key_auth),
        Depends(require_admin_permission),
        Depends(rate_limit),
    ],
)
async def revoke_key(request: Request, key_id: str) -> None:
    """Revoke a key of the caller's entity.  Soft delete: the auth query
    filters ``is_active=True``, so the key is rejected with 401 immediately."""
    from sqlalchemy import select

    from emerald.models.api_key import ApiKey

    try:
        key_uuid = UUID(key_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Key not found") from None

    async with session_factory.session() as session:
        result = await session.execute(select(ApiKey).where(ApiKey.id == key_uuid))
        record = result.scalar_one_or_none()
        if not record:
            raise HTTPException(status_code=404, detail="Key not found")

        # Entity scope: internal UUID vs internal UUID (see create_key).
        _authorize_entity(request, str(record.entity_id))

        record.is_active = False
        await session.commit()
