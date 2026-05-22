"""Base connector interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class SyncMode(str, Enum):
    INCREMENTAL = "incremental"
    FULL = "full"


@dataclass
class ConnectorCredentials:
    access_token: str
    refresh_token: str | None = None
    token_type: str = "Bearer"
    expires_at: datetime | None = None
    scopes: list[str] = field(default_factory=list)


@dataclass
class SyncResult:
    provider: str
    files_synced: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


@dataclass
class ConnectorStatus:
    provider: str
    connected: bool = False
    sync_status: str = "inactive"  # active | paused | revoked | error
    last_synced_at: datetime | None = None
    error_message: str | None = None


class BaseConnector(ABC):
    """Abstract base for all external data source connectors.

    Each connector implements OAuth flow, sync logic, webhook handling,
    and cleanup for one provider (Google Drive, Gmail, Notion, GitHub, etc.).
    """

    provider: str
    entity_id: str
    credentials: ConnectorCredentials | None = None

    @abstractmethod
    async def get_auth_url(self, redirect_uri: str) -> tuple[str, str]:
        """Get OAuth authorization URL. Returns (auth_url, state_token)."""

    @abstractmethod
    async def handle_callback(self, code: str, state: str) -> ConnectorCredentials:
        """Exchange authorization code for tokens."""

    @abstractmethod
    async def sync(self, mode: SyncMode = SyncMode.INCREMENTAL) -> SyncResult:
        """Execute sync (incremental or full)."""

    @abstractmethod
    async def handle_webhook(self, payload: dict, signature: str) -> bool:
        """Process external webhook notification. Returns True if sync triggered."""

    @abstractmethod
    async def revoke(self) -> None:
        """Revoke OAuth grant and clean up stored credentials."""

    @abstractmethod
    async def status(self) -> ConnectorStatus:
        """Return current connector status."""
