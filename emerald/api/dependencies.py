"""API authentication dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status


async def api_key_auth(request: Request) -> str:
    """Authenticate request via Bearer API key.

    TODO: Implement actual key validation against PostgreSQL api_keys table.
    Currently a stub that accepts any em_ prefixed key.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer em_"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key. Use: Bearer em_<key>",
        )

    # TODO: hash key, query api_keys table, validate permissions + expiry
    # request.state.entity_id = key_record.entity_id
    # request.state.permissions = key_record.permissions

    return "authenticated"


async def require_write_permission(request: Request) -> str:
    """Require write permission (for add/upload endpoints)."""
    # TODO: check request.state.permissions for "write"
    return "authenticated"
