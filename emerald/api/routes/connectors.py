"""Connector routes — OAuth flow, webhooks, status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from emerald.api.dependencies import api_key_auth, require_write_permission

router = APIRouter(
    prefix="/connectors",
    tags=["Connectors"],
)


@router.post(
    "/{provider}/connect",
    response_model=dict,
    dependencies=[Depends(api_key_auth), Depends(require_write_permission)],
)
async def connect_provider(provider: str) -> dict:
    """Initiate OAuth connection to an external data source.

    Providers: google_drive, gmail, notion, github.
    Returns the OAuth authorization URL for the user to visit.
    """
    valid_providers = {"google_drive", "gmail", "notion", "github"}
    if provider not in valid_providers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown provider '{provider}'. Valid: {valid_providers}",
        )
    # TODO: delegate to connector registry
    return {
        "data": {
            "provider": provider,
            "auth_url": "",
            "state_token": "",
            "expires_in": 600,
        },
    }


@router.post(
    "/{provider}/webhook",
    response_model=dict,
)
async def handle_webhook(provider: str, request: Request) -> dict:
    """Receive webhook notifications from external providers.

    Validates signature, deduplicates, triggers incremental sync.
    """
    # TODO: signature verification, event dedup, sync trigger
    return {"status": "accepted"}


@router.get(
    "/{provider}",
    response_model=dict,
    dependencies=[Depends(api_key_auth)],
)
async def get_connector_status(provider: str) -> dict:
    """Get connector sync status for the authenticated entity."""
    return {
        "data": {
            "provider": provider,
            "sync_status": "active",
            "last_synced_at": None,
            "error_message": None,
            "connected_at": None,
        },
    }


@router.delete(
    "/{provider}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(api_key_auth), Depends(require_write_permission)],
)
async def revoke_connector(provider: str) -> None:
    """Revoke OAuth connection and delete stored credentials."""
    # TODO: revoke tokens, clean up connector record
    pass
