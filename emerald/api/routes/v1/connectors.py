"""Connector routes - OAuth flow, webhooks, status."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy import select

from emerald.api._state_store import OAuthStateStore
from emerald.api.dependencies import api_key_auth, require_write_permission
from emerald.connectors.auth import encrypt_credentials
from emerald.connectors.registry import get_connector_registry
from emerald.db.session import session_factory
from emerald.models.connector import Connector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connectors", tags=["Connectors"])


# Single shared instance.  TTL is read from settings (see I8 fix).
_oauth_state_store = OAuthStateStore()


# ---- Helper: resolve entity from request state ----

def _get_entity_id(request: Request) -> str:
    return getattr(request.state, "entity_id", "")


def _get_oauth_redis() -> Redis:
    """Get the Redis client used for OAuth state.  Raises 503 if unavailable."""
    try:
        from emerald.db.redis import get_redis_client
        return get_redis_client()
    except RuntimeError as exc:
        # Redis not initialised — fail loudly rather than fall back to the
        # broken in-memory dict.  See P2.1 fix.
        raise HTTPException(
            status_code=503,
            detail="OAuth state store unavailable (Redis not initialised)",
        ) from exc


# ---- OAuth Connect ----

@router.post(
    "/{provider}/connect",
    response_model=dict,
    dependencies=[Depends(api_key_auth), Depends(require_write_permission)],
)
async def connect_provider(
    provider: str,
    request: Request,
    redirect_uri: str = "",
) -> dict:
    """Initiate OAuth connection to an external data source.

    Providers: google_drive, gmail, notion, github.
    Returns the OAuth authorization URL for the user to visit.
    """
    start = time.perf_counter()
    valid_providers = {"google_drive", "gmail", "notion", "github"}
    if provider not in valid_providers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown provider '{provider}'. Valid: {valid_providers}",
        )

    registry = get_connector_registry()
    connector_cls = registry.get(provider)
    entity_id = _get_entity_id(request)
    connector = connector_cls(entity_id=entity_id)

    # Default redirect URI if not provided
    if not redirect_uri:
        from emerald.config import get_settings
        base = get_settings().emerald_env == "production" and "https://api.emerald.ai" or "http://localhost:8000"
        redirect_uri = f"{base}/v1/connectors/{provider}/callback"

    auth_url, state_token = await connector.get_auth_url(redirect_uri)
    redis = _get_oauth_redis()
    await _oauth_state_store.put(redis, state_token, entity_id)

    return {
        "data": {
            "provider": provider,
            "auth_url": auth_url,
            "state_token": state_token,
            "expires_in": 600,
        },
        "meta": {
            "request_id": getattr(request.state, "request_id", str(uuid.uuid4())[:8]),
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


# ---- OAuth Callback ----

@router.get(
    "/{provider}/callback",
    response_model=dict,
)
async def handle_oauth_callback(
    provider: str,
    code: str,
    state: str,
    request: Request,
) -> dict:
    """OAuth callback - exchange code for token and store credentials."""
    start = time.perf_counter()
    registry = get_connector_registry()
    connector_cls = registry.get(provider)

    # Resolve entity_id from the state token stored during connect_provider.
    # P2.1: read from Redis (multi-worker safe) and delete after use.
    redis = _get_oauth_redis()
    entity_id = await _oauth_state_store.consume(redis, state)
    if not entity_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired state token",
        )

    connector = connector_cls(entity_id=entity_id)
    creds = await connector.handle_callback(code, state)

    # Encrypt and store credentials
    encrypted = encrypt_credentials(creds)

    async with session_factory.session() as session:
        result = await session.execute(
            select(Connector).where(
                Connector.entity_id == uuid.UUID(entity_id),
                Connector.provider == provider,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.credentials = encrypted
            existing.sync_status = "active"
            existing.error_message = None
        else:
            session.add(
                Connector(
                    entity_id=uuid.UUID(entity_id),
                    provider=provider,
                    credentials=encrypted,
                    sync_status="active",
                )
            )
        await session.commit()

    return {
        "data": {
            "provider": provider,
            "status": "connected",
            "entity_id": entity_id,
        },
        "meta": {
            "request_id": str(uuid.uuid4())[:8],
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


# ---- Webhook ----

@router.post(
    "/{provider}/webhook",
    response_model=dict,
)
async def handle_webhook(
    provider: str,
    request: Request,
) -> dict:
    """Receive webhook notifications from external providers.

    Validates signature, deduplicates, triggers incremental sync.
    """
    start = time.perf_counter()
    raw_body = await request.body()
    payload = await request.json()
    payload["_raw_body"] = raw_body

    signature = request.headers.get("X-Hub-Signature-256", "")

    registry = get_connector_registry()
    connector_cls = registry.get(provider)

    # For webhooks, entity_id is typically encoded in the webhook path or payload
    entity_id = payload.get("repository", {}).get("owner", {}).get("login", "")
    connector = connector_cls(entity_id=entity_id)

    triggered = await connector.handle_webhook(payload, signature)

    return {
        "data": {
            "status": "accepted",
            "sync_triggered": triggered,
        },
        "meta": {
            "request_id": getattr(request.state, "request_id", str(uuid.uuid4())[:8]),
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


# ---- Status ----

@router.get(
    "/{provider}",
    response_model=dict,
    dependencies=[Depends(api_key_auth)],
)
async def get_connector_status(
    provider: str,
    request: Request,
) -> dict:
    """Get connector sync status for the authenticated entity."""
    start = time.perf_counter()
    entity_id = _get_entity_id(request)

    async with session_factory.session() as session:
        result = await session.execute(
            select(Connector).where(
                Connector.entity_id == uuid.UUID(entity_id),
                Connector.provider == provider,
            )
        )
        row = result.scalar_one_or_none()

    if not row:
        return {
            "data": {
                "provider": provider,
                "sync_status": "inactive",
                "last_synced_at": None,
                "error_message": None,
                "connected_at": None,
            },
        }

    return {
        "data": {
            "provider": row.provider,
            "sync_status": row.sync_status,
            "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
            "error_message": row.error_message,
            "connected_at": row.created_at.isoformat() if row.created_at else None,
        },
        "meta": {
            "request_id": getattr(request.state, "request_id", str(uuid.uuid4())[:8]),
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


# ---- Revoke ----

@router.delete(
    "/{provider}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(api_key_auth), Depends(require_write_permission)],
)
async def revoke_connector(
    provider: str,
    request: Request,
) -> None:
    """Revoke OAuth connection and delete stored credentials."""
    entity_id = _get_entity_id(request)

    async with session_factory.session() as session:
        result = await session.execute(
            select(Connector).where(
                Connector.entity_id == uuid.UUID(entity_id),
                Connector.provider == provider,
            )
        )
        row = result.scalar_one_or_none()

        if row:
            # Decrypt and revoke tokens
            from emerald.connectors.auth import decrypt_credentials
            from emerald.connectors.registry import get_connector_registry

            registry = get_connector_registry()
            connector_cls = registry.get(provider)
            connector = connector_cls(entity_id=entity_id)
            connector.credentials = decrypt_credentials(row.credentials)
            await connector.revoke()

            await session.delete(row)
            await session.commit()
