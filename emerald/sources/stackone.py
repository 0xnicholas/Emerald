"""StackOne — first ConnectionHub implementation (ADR-0004).

Implements the contract in :mod:`emerald.sources.hub` against StackOne's
Platform API (Basic auth = API key id/secret; per-account actions via the
RPC layer; webhook deliveries signed with HMAC-SHA256 over the raw body
in the ``x-stackone-signature`` header, base64url-encoded).

Endpoint paths follow StackOne's API catalog
(https://docs.stackone.com/.well-known/api-catalog). If a path drifts,
fix it here — nowhere else in Emerald.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any

import httpx
import structlog

from emerald.config import get_settings
from emerald.sources.hub import (
    ConnectionHub,
    ConnectionHubAuthError,
    ConnectionHubError,
    ConnectSession,
    HubAccount,
    HubEvent,
)

logger = structlog.get_logger(__name__)

# ---- Platform API endpoints (per StackOne API catalog) ----
CONNECT_SESSIONS_PATH = "/connect_sessions"
ACCOUNTS_PATH = "/accounts"
ACTIONS_RPC_PATH = "/actions/rpc"

# ---- Outbound events ----
# StackOne delivers events to the webhook endpoint; the normalized
# event_type is derived from the payload's `event`/`type` field, with a
# provider/account fallback so a real account's deliveries can be mapped
# to the HubEvent contract (pilot: verify against live delivery).
SIGNATURE_HEADER = "x-stackone-signature"


class StackOneHubClient(ConnectionHub):
    """StackOne implementation of the ConnectionHub contract."""

    def __init__(
        self,
        *,
        api_base_url: str | None = None,
        api_key_id: str | None = None,
        api_key_secret: str | None = None,
        webhook_secret: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        settings = get_settings()
        self._api_base_url = (api_base_url or settings.stackone_api_base_url).rstrip("/")
        key_id = api_key_id or settings.stackone_api_key_id
        key_secret = api_key_secret or settings.stackone_api_key_secret
        self._webhook_secret = webhook_secret or settings.stackone_webhook_secret
        if not key_id:
            logger.warning(
                "stackone_api_key_id not configured; "
                "hub calls will fail with 401"
            )
        token = base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()
        self._client = httpx.AsyncClient(
            base_url=self._api_base_url,
            headers={"Authorization": f"Basic {token}"},
            timeout=timeout,
        )

    # ---- ConnectionHub contract ----

    async def create_connect_session(
        self,
        *,
        origin_owner_id: str,
        origin_owner_name: str,
        provider: str,
        metadata: dict[str, Any] | None = None,
    ) -> ConnectSession:
        resp = await self._post(
            CONNECT_SESSIONS_PATH,
            json={
                "origin_owner_id": origin_owner_id,
                "origin_owner_name": origin_owner_name,
                "provider": provider,
                "expires_in": 1800,
                "metadata": metadata or {},
            },
        )
        return ConnectSession(
            id=str(resp.get("id", "")),
            url=resp.get("auth_link_url", ""),
            token=resp.get("token", ""),
            expires_in=resp.get("expires_in", 1800),
            provider=resp.get("provider") or provider,
            metadata=metadata or {},
        )

    async def list_accounts(self, origin_owner_id: str) -> list[HubAccount]:
        resp = await self._get(ACCOUNTS_PATH, params={"origin_owner_id": origin_owner_id})
        data = resp.get("data", resp if isinstance(resp, list) else [])
        if isinstance(data, dict):
            data = data.get("results", [])
        accounts = []
        for item in data:
            accounts.append(
                HubAccount(
                    id=item.get("id") or item.get("account_id") or "",
                    provider=item.get("provider", ""),
                    origin_owner_id=item.get("origin_owner_id") or origin_owner_id,
                    status=item.get("status", "active"),
                    created_at=None,
                )
            )
        return accounts

    async def execute_action(
        self,
        *,
        account_id: str,
        action: str,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._post(
            ACTIONS_RPC_PATH,
            json={
                "action": action,
                "query": query or {},
                "body": body or {},
            },
            headers={"x-account-id": account_id},
        )

    async def verify_webhook(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> bool:
        if not self._webhook_secret:
            logger.warning("stackone_webhook_secret not configured; rejecting webhook")
            return False
        signature = headers.get(SIGNATURE_HEADER, "")
        if not signature:
            return False
        expected = base64.urlsafe_b64encode(
            hmac.new(
                self._webhook_secret.encode(),
                raw_body,
                hashlib.sha256,
            ).digest()
        ).decode()
        return hmac.compare_digest(signature, expected)

    async def parse_event(self, raw_body: bytes) -> HubEvent:
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise ConnectionHubError(f"invalid webhook JSON: {exc}") from exc

        # StackOne event envelope: {event, account_id, provider, payload, ...}
        # Field names are read tolerantly so a live delivery maps cleanly.
        event_type = (
            payload.get("event")
            or payload.get("type")
            or payload.get("event_type")
            or "unknown"
        )
        account = payload.get("account") or {}
        provider = payload.get("provider") or account.get("provider") or ""
        account_id = (
            payload.get("account_id")
            or account.get("id")
            or account.get("account_id")
            or ""
        )
        origin_owner_id = (
            payload.get("origin_owner_id")
            or account.get("origin_owner_id")
        )
        inner = payload.get("payload", payload)
        if isinstance(inner, dict) and "payload" in inner:
            inner = inner["payload"]
        return HubEvent(
            event_type=str(event_type),
            provider=str(provider),
            account_id=str(account_id),
            origin_owner_id=origin_owner_id,
            payload=inner if isinstance(inner, dict) else {"raw": inner},
            raw=raw_body,
        )

    # ---- HTTP helpers ----

    async def _post(
        self,
        path: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            resp = await self._client.post(path, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise ConnectionHubError(f"hub request failed: {exc}") from exc
        return self._raise_for_status(resp)

    async def _get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            resp = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise ConnectionHubError(f"hub request failed: {exc}") from exc
        return self._raise_for_status(resp)

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code in (401, 403):
            raise ConnectionHubAuthError(
                f"hub auth failed ({resp.status_code}): {resp.text[:200]}"
            )
        if resp.status_code >= 400:
            raise ConnectionHubError(
                f"hub error {resp.status_code}: {resp.text[:300]}"
            )
        return resp.json() if resp.content else {}

    async def aclose(self) -> None:
        await self._client.aclose()

    @classmethod
    def from_settings(cls) -> StackOneHubClient:
        """Build the client from application settings."""
        settings = get_settings()
        return cls(
            api_base_url=settings.stackone_api_base_url,
            api_key_id=settings.stackone_api_key_id,
            api_key_secret=settings.stackone_api_key_secret,
            webhook_secret=settings.stackone_webhook_secret,
        )
