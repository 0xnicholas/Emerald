"""Totem — ConnectionHub implementation against the internal action layer.

Implements the contract in :mod:`emerald.sources.hub` against Totem
(../totem, ADR-0004): a self-hosted multi-tenant action layer whose v1
upstream is Feishu Docs. Contract source is Totem's consumption standard
(``docs/standards/consumption-standard.md``) and the machine-readable
``GET {TOTEM_URL}/openapi.json`` — if a path or envelope drifts, fix it
here — nowhere else in Emerald.

Two credential surfaces (standard §1/§5, totem's ADR-0010 trust model):

- **actions-scope key** (``TOTEM_API_KEY``): every ``POST /actions/rpc``
  call, ``Authorization: Bearer`` + ``x-connection-id``.
- **admin-scope key** (``TOTEM_ADMIN_KEY``): only the two binding-lifecycle
  calls — ``POST /admin/tenants/{tenant}/oauth/start`` (authorize flow) and
  ``GET /admin/tenants/{tenant}/connections`` (reconciliation). Admin keys
  are platform-credential-equivalent; they are never used for daily RPC.

Entity mapping (pilot): one Totem tenant per Emerald deployment
(``TOTEM_TENANT_ID``); an Emerald entity's linked accounts are Totem
*connections* inside that tenant (``hub_account_id`` = connection id).

Webhooks: Totem v1 is a pull-only action layer with no webhook delivery
(ADR-0011); Emerald keeps its own upstream subscription as the "bell" and
normalizes events into the platform's pre-recorded v2 shape (§8.2).
Signature verification implements the reserved contract verbatim
(HMAC-SHA256 over the raw body, base64url, ``x-totem-signature``,
constant-time compare) so the v2 migration is an entry-point swap.
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

# ---- Endpoints (per Totem consumption standard §1/§5) ----
ACTIONS_RPC_PATH = "/actions/rpc"
OAUTH_START_PATH = "/admin/tenants/{tenant_id}/oauth/start"
CONNECTIONS_PATH = "/admin/tenants/{tenant_id}/connections"

# ---- Inbound event signature (standard §8.3, pre-recorded v2 contract) ----
SIGNATURE_HEADER = "x-totem-signature"

# Provider key for the only v1 upstream (standard §0, Feishu Docs).
FEISHU_PROVIDER = "feishu"


class TotemHubClient(ConnectionHub):
    """Totem implementation of the ConnectionHub contract."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        admin_key: str | None = None,
        tenant_id: str | None = None,
        webhook_secret: str | None = None,
        oauth_redirect_uri: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.totem_base_url).rstrip("/")
        self._tenant_id = tenant_id or settings.totem_tenant_id
        self._api_key = api_key if api_key is not None else settings.totem_api_key
        self._admin_key = admin_key if admin_key is not None else settings.totem_admin_key
        self._webhook_secret = (
            webhook_secret if webhook_secret is not None else settings.totem_webhook_secret
        )
        self._oauth_redirect_uri = oauth_redirect_uri or settings.totem_oauth_redirect_uri
        if not self._api_key:
            logger.warning("totem_api_key not configured; RPC calls will fail with 401")
        if not self._admin_key:
            logger.warning("totem_admin_key not configured; connect/refresh calls will fail")
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=timeout)

    # ---- ConnectionHub contract ----

    async def create_connect_session(
        self,
        *,
        origin_owner_id: str,
        origin_owner_name: str,
        provider: str,
        metadata: dict[str, Any] | None = None,
    ) -> ConnectSession:
        """Open Totem's authorize flow for the deployment tenant.

        Totem has no session token (its flow is one redirect, ADR-0007);
        ``session_id`` is the tenant id so callers keep a stable handle.
        The Emerald entity is recorded in ``metadata`` only — connections
        belong to the tenant, bindings to the entity.
        """
        redirect_uri = self._oauth_redirect_uri or f"{self._base_url}/oauth/callback/feishu"
        body: dict[str, Any] = {"redirectUri": redirect_uri}
        if metadata and metadata.get("connection_id"):
            body["connectionId"] = metadata["connection_id"]
        resp = await self._admin_post(OAUTH_START_PATH.format(tenant_id=self._tenant_id), json=body)
        return ConnectSession(
            id=self._tenant_id,
            url=resp.get("authorizationUrl", ""),
            token="",
            expires_in=0,
            provider=provider or FEISHU_PROVIDER,
            metadata={
                "tenant_id": self._tenant_id,
                "entity_id": origin_owner_id,
                **(metadata or {}),
            },
        )

    async def list_accounts(self, origin_owner_id: str) -> list[HubAccount]:
        """List the deployment tenant's connections (the entity's accounts)."""
        resp = await self._admin_get(CONNECTIONS_PATH.format(tenant_id=self._tenant_id))
        data = resp.get("connections", [])
        if isinstance(data, dict):
            data = data.get("connections", []) or data.get("data", [])
        accounts = []
        for item in data if isinstance(data, list) else []:
            accounts.append(
                HubAccount(
                    id=item.get("id") or item.get("connection_id") or "",
                    provider=item.get("connector_id") or FEISHU_PROVIDER,
                    origin_owner_id=item.get("owner_id") or origin_owner_id,
                    status=_normalize_status(item.get("status")),
                    created_at=_parse_datetime(item.get("created_at")),
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
        """Execute one action on Totem's RPC surface.

        Totem's envelope is ``{action, args}`` with flat schema-first args
        (standard §2) — the five-part StackOne envelope does not exist;
        ``query``/``body`` are merged into ``args`` here so the abstract
        interface stays untouched. The connection is selected per request
        via ``x-connection-id``.
        """
        args: dict[str, Any] = {}
        if body:
            args.update(body)
        if query:
            args.update(query)
        resp = await self._post(
            ACTIONS_RPC_PATH,
            json={"action": action, "args": args},
            headers={"x-connection-id": account_id},
        )
        if not isinstance(resp, dict):
            raise ConnectionHubError(f"totem RPC returned non-object: {resp!r}")
        return resp

    async def verify_webhook(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> bool:
        """Verify a delivery signature per the pre-recorded v2 contract.

        HMAC-SHA256 over the raw request body, base64url, compared in
        constant time (standard §8.3 — identical to the v2 platform
        delivery; v1 direct-subscription period uses the same shape).
        """
        if not self._webhook_secret:
            logger.warning("totem_webhook_secret not configured; rejecting webhook")
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
        """Normalize a delivery into the standard platform event shape (§8.2).

        The envelope is ``{event, tenant_id, connection_id, record_type,
        record_id, provider, event_date, sent_at}``; v1 upstream events are
        mapped onto it by the subscriber before delivery, so parsing here
        is the same code the v2 platform webhook will hit.
        """
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise ConnectionHubError(f"invalid webhook JSON: {exc}") from exc

        event_type = (
            payload.get("event") or payload.get("type") or payload.get("event_type") or "unknown"
        )
        account = payload.get("account") or payload.get("connection") or {}
        provider = payload.get("provider") or account.get("provider") or FEISHU_PROVIDER
        account_id = (
            payload.get("connection_id")
            or payload.get("account_id")
            or account.get("id")
            or account.get("connection_id")
            or ""
        )
        origin_owner_id = (
            payload.get("tenant_id")
            or payload.get("origin_owner_id")
            or account.get("tenant_id")
            or account.get("origin_owner_id")
        )
        envelope_keys = {
            "event",
            "type",
            "event_type",
            "tenant_id",
            "connection_id",
            "account_id",
            "record_type",
            "record_id",
            "provider",
            "event_date",
            "sent_at",
            "origin_owner_id",
            "origin_owner_name",
        }
        inner = payload.get("payload", payload)
        if isinstance(inner, dict) and "payload" in inner:
            inner = inner["payload"]
        if isinstance(inner, dict):
            inner = {k: v for k, v in inner.items() if k not in envelope_keys}
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
        return await self._request(
            "POST",
            path,
            json=json,
            headers={"Authorization": f"Bearer {self._api_key}", **(headers or {})},
        )

    async def _admin_post(
        self,
        path: str,
        *,
        json: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            path,
            json=json,
            headers={"Authorization": f"Bearer {self._admin_key}"},
        )

    async def _admin_get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            path,
            params=params,
            headers={"Authorization": f"Bearer {self._admin_key}"},
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        try:
            resp = await self._client.request(
                method, path, json=json, params=params, headers=headers
            )
        except httpx.HTTPError as exc:
            raise ConnectionHubError(f"hub request failed: {exc}") from exc
        return self._raise_for_status(resp)

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> dict[str, Any]:
        """Map Totem's unified error vocabulary (standard §4) to hub errors.

        Seven codes, HTTP-mapped: 400 validation / 403 forbidden /
        404 action_not_found+not_found / 429 rate_limited / 502
        upstream_error; ``retryable`` is surfaced in the message so
        callers can honor backoff. Only 401 rejects our credentials.
        """
        if resp.status_code in (401, 403):
            raise ConnectionHubAuthError(f"hub auth failed ({resp.status_code}): {resp.text[:200]}")
        if resp.status_code >= 400:
            detail = resp.text[:300]
            try:
                error = resp.json()
                if isinstance(error, dict):
                    code = error.get("code") or resp.status_code
                    retryable = error.get("retryable", False)
                    retry_after = error.get("retryAfterSeconds")
                    detail = f"{code}: {error.get('message', detail)}"
                    if retry_after is not None:
                        detail += f" (retryable={retryable}, retryAfterSeconds={retry_after})"
            except ValueError:
                pass
            raise ConnectionHubError(f"hub error {resp.status_code}: {detail}")
        return resp.json() if resp.content else {}

    async def aclose(self) -> None:
        await self._client.aclose()

    @classmethod
    def from_settings(cls) -> TotemHubClient:
        """Build the client from application settings."""
        settings = get_settings()
        return cls(
            base_url=settings.totem_base_url,
            api_key=settings.totem_api_key,
            admin_key=settings.totem_admin_key,
            tenant_id=settings.totem_tenant_id,
            webhook_secret=settings.totem_webhook_secret,
            oauth_redirect_uri=settings.totem_oauth_redirect_uri,
        )


def _normalize_status(status: Any) -> str:
    """Map a Totem connection status onto the HubAccount vocabulary."""
    value = str(status or "active").lower()
    if value in ("active", "ok", "healthy"):
        return "active"
    if value in ("revoked", "disconnected", "suspended", "suspended_user"):
        return "revoked"
    if value in ("error", "failed", "auth_expired"):
        return "error"
    return value


def _parse_datetime(value: Any) -> Any:
    if not value:
        return None
    try:
        from datetime import datetime

        text = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except ValueError:
        return None
