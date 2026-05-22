"""Gmail connector — email sync via Google OAuth and Pub/Sub."""

from __future__ import annotations

from emerald.connectors.base import (
    BaseConnector,
    ConnectorCredentials,
    ConnectorStatus,
    SyncMode,
    SyncResult,
)


class GmailConnector(BaseConnector):
    """Syncs emails from Gmail via Google OAuth and GCP Pub/Sub."""

    provider = "gmail"

    async def get_auth_url(self, redirect_uri: str) -> tuple[str, str]:
        raise NotImplementedError

    async def handle_callback(self, code: str, state: str) -> ConnectorCredentials:
        raise NotImplementedError

    async def sync(self, mode: SyncMode = SyncMode.INCREMENTAL) -> SyncResult:
        raise NotImplementedError

    async def handle_webhook(self, payload: dict, signature: str) -> bool:
        raise NotImplementedError

    async def revoke(self) -> None:
        raise NotImplementedError

    async def status(self) -> ConnectorStatus:
        raise NotImplementedError
