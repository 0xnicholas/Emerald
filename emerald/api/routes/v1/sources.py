"""Source binding routes (ADR-0004) — connection hub flow.

Replaces the self-built connector OAuth flow: Emerald opens a connect
session on the hub, the user authorizes there, and the binding is
created when the hub's ``account.connected`` event arrives (or via
``POST /v1/sources/refresh`` reconciliation).
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from emerald.api.dependencies import (
    api_key_auth,
    authorize_entity,
    rate_limit,
    require_write_permission,
)
from emerald.sources import binding_store
from emerald.sources.factory import get_hub
from emerald.sources.hub import ConnectionHubError

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/sources", tags=["Sources"])

VALID_PROVIDERS = {"googledrive", "notion", "gmail", "github"}


class ConnectRequest(BaseModel):
    entity_id: str = Field(..., description="Entity that will own the binding")
    provider: str = Field(
        ...,
        description="Provider key on the hub (googledrive, notion, gmail, github)",
    )


class ConnectResponse(BaseModel):
    auth_link_url: str
    session_id: str
    provider: str


def _entity_from_request(request: Request, entity_id: str) -> str:
    """Validate the entity is visible to the authenticated key."""
    authorize_entity(request, entity_id)
    return entity_id


@router.post(
    "/connect",
    dependencies=[Depends(api_key_auth), Depends(require_write_permission), Depends(rate_limit)],
)
async def create_connect_session(
    body: ConnectRequest,
    request: Request,
) -> dict:
    """Open the account-linking flow: returns the hub's auth link.

    The end user is sent to ``auth_link_url``; after authorizing, the
    hub delivers an ``account.connected`` event to the webhook endpoint
    and the binding is created.
    """
    if body.provider not in VALID_PROVIDERS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown provider '{body.provider}'. Valid: {sorted(VALID_PROVIDERS)}",
        )
    _entity_from_request(request, body.entity_id)
    hub = get_hub()
    try:
        session = await hub.create_connect_session(
            origin_owner_id=body.entity_id,
            origin_owner_name=body.entity_id,
            provider=body.provider,
            metadata={"entity_id": body.entity_id},
        )
    except ConnectionHubError as exc:
        logger.warning("hub_connect_session_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Hub connect session failed: {exc}") from exc
    return {
        "data": {
            "auth_link_url": session.url,
            "session_id": session.id,
            "provider": body.provider,
        }
    }


@router.post(
    "/webhook",
    dependencies=[Depends(rate_limit)],
)
async def receive_webhook(request: Request) -> dict:
    """Hub event delivery endpoint.

    Signed by the hub (HMAC-SHA256 over the raw body); no API key — the
    signature is the credential. Events trigger incremental ingestion.
    """
    raw_body = await request.body()
    hub = get_hub()
    if not await hub.verify_webhook(raw_body, request.headers):
        logger.warning("hub_webhook_signature_invalid")
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = await hub.parse_event(raw_body)
    logger.info(
        "hub_event_received",
        event_type=event.event_type,
        provider=event.provider,
        account_id=event.account_id,
    )

    from emerald.sources.adapter import HubAdapter, default_content_cb

    adapter = HubAdapter(hub)
    result = await adapter.handle_event(event, content_cb=default_content_cb())
    return {
        "data": {
            "event_type": event.event_type,
            "provider": result.provider,
            "account_id": result.account_id,
            "ingested": result.ingested,
            "skipped": result.skipped,
            "failed": result.failed,
            "errors": result.errors[:5],
        }
    }


@router.get(
    "",
    dependencies=[Depends(api_key_auth), Depends(rate_limit)],
)
async def list_sources(entity_id: str, request: Request) -> dict:
    """List source bindings for an entity."""
    _entity_from_request(request, entity_id)
    bindings = await binding_store.list_bindings(entity_id)
    return {
        "data": [
            {
                "id": str(b.id),
                "provider": b.provider,
                "hub_account_id": b.hub_account_id,
                "sync_status": b.sync_status,
                "last_synced_at": b.last_synced_at.isoformat() if b.last_synced_at else None,
                "error_message": b.error_message,
            }
            for b in bindings
        ]
    }


@router.post(
    "/refresh",
    dependencies=[Depends(api_key_auth), Depends(require_write_permission), Depends(rate_limit)],
)
async def refresh_sources(entity_id: str, request: Request) -> dict:
    """Reconcile bindings with the hub: upsert newly authorized accounts.

    Call this after the user returns from the hub's auth link as a
    belt-and-suspenders path (the ``account.connected`` webhook is the
    primary one).
    """
    _entity_from_request(request, entity_id)
    hub = get_hub()
    try:
        accounts = await hub.list_accounts(entity_id)
    except ConnectionHubError as exc:
        logger.warning("hub_list_accounts_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Hub accounts failed: {exc}") from exc

    created: list[str] = []
    for account in accounts:
        if not account.id:
            continue
        binding = await binding_store.upsert_binding(
            entity_id=entity_id,
            provider=account.provider,
            hub_account_id=account.id,
        )
        created.append(str(binding.id))
    return {"data": {"accounts": len(accounts), "bindings": created}}


@router.delete(
    "/{binding_id}",
    dependencies=[Depends(api_key_auth), Depends(require_write_permission), Depends(rate_limit)],
)
async def delete_source(binding_id: uuid.UUID, entity_id: str, request: Request) -> dict:
    """Remove a source binding (data stays in the graph; new syncs stop)."""
    _entity_from_request(request, entity_id)
    await binding_store.delete_binding(binding_id)
    return {"data": {"deleted": True, "binding_id": str(binding_id)}}
