"""API key management schemas (issue #5)."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator

from emerald.api.schemas.common import PaginationMeta

ALLOWED_PERMISSIONS = ("read", "write", "admin")


class _Meta(BaseModel):
    request_id: str
    took_ms: int


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

    @field_validator("permissions")
    @classmethod
    def _validate_permissions(cls, value: list[str]) -> list[str]:
        if not value or not set(value) <= set(ALLOWED_PERMISSIONS):
            raise ValueError(
                f"permissions must be a non-empty subset of {list(ALLOWED_PERMISSIONS)}"
            )
        return sorted(set(value))

    @field_validator("expires_at")
    @classmethod
    def _coerce_aware(cls, value: datetime | None) -> datetime | None:
        """Naive datetimes are interpreted as UTC.

        The stored column is timestamptz and the auth check compares
        against ``datetime.now(UTC)``; a naive value would raise on
        comparison instead of expiring (issue #5 review).
        """
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


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


class CreateKeyEnvelope(BaseModel):
    data: CreateKeyResponse
    meta: _Meta


class ListKeysData(BaseModel):
    items: list[KeyMetadata]
    page_size: int


class ListKeysEnvelope(BaseModel):
    data: ListKeysData
    meta: _Meta
    pagination: PaginationMeta
