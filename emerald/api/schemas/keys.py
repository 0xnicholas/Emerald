"""API key management schemas (issue #5)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

ALLOWED_PERMISSIONS = ("read", "write", "admin")


class CreateKeyRequest(BaseModel):
    """Create a new API key for the caller's entity.

    ``entity_id`` is the external entity id and must match the caller's
    own entity (management is entity-scoped: an admin key manages keys
    within its own entity only).
    """

    entity_id: str = Field(description="External entity id the key is scoped to")
    permissions: list[str] = Field(
        description=f"Permission levels: {', '.join(ALLOWED_PERMISSIONS)}",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Optional expiry; the key returns 401 after this time",
    )


class KeyMetadata(BaseModel):
    """Key metadata for list responses — never carries the hash or the
    raw key (they are not recoverable by design)."""

    key_id: str
    key_prefix: str
    permissions: list[str]
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    is_active: bool
    created_at: datetime | None = None


class CreateKeyResponse(BaseModel):
    """Create response.  ``key`` (plaintext) appears exactly once — the
    server stores only its SHA-256 hash and cannot recover it."""

    key: str
    key_id: str
    key_prefix: str
    permissions: list[str]
    expires_at: datetime | None = None
    entity_id: str
