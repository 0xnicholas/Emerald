"""GitHub connector — repository and issue sync via GitHub App."""

from __future__ import annotations

from emerald.connectors.base import (
    BaseConnector,
    ConnectorCredentials,
    ConnectorStatus,
    SyncMode,
    SyncResult,
)


class GitHubConnector(BaseConnector):
    """Syncs GitHub repositories, code, issues, PRs, and discussions."""

    provider = "github"

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
