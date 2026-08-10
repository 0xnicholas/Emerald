"""FakeHub — in-memory ConnectionHub implementation for tests.

Exercises the contract without HTTP. Also ships an in-memory binding
store so adapter/route tests don't need a database.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any

from emerald.sources.hub import (
    ConnectionHub,
    ConnectSession,
    HubAccount,
    HubEvent,
)


class FakeHub(ConnectionHub):
    """Deterministic in-memory hub.

    ``accounts`` maps origin_owner_id -> list of accounts.
    ``listings`` maps account_id -> list of raw items (list_action).
    ``contents`` maps (account_id, source_id) -> raw content dict (get_action).
    """

    def __init__(
        self,
        *,
        webhook_secret: str = "test-secret",
    ) -> None:
        self.webhook_secret = webhook_secret
        self.accounts: dict[str, list[HubAccount]] = {}
        self.listings: dict[str, list[dict[str, Any]]] = {}
        self.contents: dict[str, dict[str, Any]] = {}
        self.created_sessions: list[ConnectSession] = []
        self.action_calls: list[dict[str, Any]] = []

    async def create_connect_session(
        self,
        *,
        origin_owner_id: str,
        origin_owner_name: str,
        provider: str,
        metadata: dict[str, Any] | None = None,
    ) -> ConnectSession:
        session = ConnectSession(
            id=f"session-{len(self.created_sessions) + 1}",
            url=f"https://hub.example.com/connect/{provider}?owner={origin_owner_id}",
            token=f"tok-{len(self.created_sessions) + 1}",
            provider=provider,
            metadata=metadata or {},
        )
        self.created_sessions.append(session)
        return session

    async def list_accounts(self, origin_owner_id: str) -> list[HubAccount]:
        return self.accounts.get(origin_owner_id, [])

    async def execute_action(
        self,
        *,
        account_id: str,
        action: str,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.action_calls.append(
            {"account_id": account_id, "action": action, "query": query or {}}
        )
        if action.endswith("list") or action.startswith("list"):
            return {"results": self.listings.get(account_id, [])}
        # get_action: fetch one item's content
        source_id = (query or {}).get("id")
        key = f"{account_id}:{source_id}"
        if key in self.contents:
            return self.contents[key]
        return {}

    async def verify_webhook(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> bool:
        signature = headers.get("x-stackone-signature", "")
        if not signature:
            return False
        expected = _sign(raw_body, self.webhook_secret)
        return hmac.compare_digest(signature, expected)

    async def parse_event(self, raw_body: bytes) -> HubEvent:
        payload = json.loads(raw_body)
        return HubEvent(
            event_type=payload.get("event", "unknown"),
            provider=payload.get("provider", ""),
            account_id=payload.get("account_id", ""),
            origin_owner_id=payload.get("origin_owner_id"),
            payload=payload.get("payload", {}),
            raw=raw_body,
        )


def _sign(raw_body: bytes, secret: str) -> str:
    import base64

    return base64.urlsafe_b64encode(
        hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()
    ).decode()


class FakeBinding:
    """Attribute-style stand-in for the SourceBinding ORM row."""

    def __init__(
        self, *, binding_id: str, entity_id: str, provider: str, hub_account_id: str
    ) -> None:
        self.id = binding_id
        self.entity_id = entity_id
        self.provider = provider
        self.hub_account_id = hub_account_id
        self.sync_status = "active"
        self.sync_metadata: dict | None = None
        self.error_message: str | None = None
        self.last_synced_at = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entity_id": self.entity_id,
            "provider": self.provider,
            "hub_account_id": self.hub_account_id,
            "sync_status": self.sync_status,
            "sync_metadata": self.sync_metadata,
            "error_message": self.error_message,
        }


class FakeBindingStore:
    """Dict-backed stand-in for emerald.sources.binding_store."""

    def __init__(self) -> None:
        self.bindings: dict[str, FakeBinding] = {}
        self.entity_external: dict[str, str] = {}  # internal UUID -> external_id
        self.missing_entities: set[str] = set()  # internal UUIDs with no entity row
        self._next_id = 1

    async def get_entity_external_id(self, entity_internal_id: str) -> str | None:
        if entity_internal_id in self.missing_entities:
            return None
        if entity_internal_id in self.entity_external:
            return self.entity_external[entity_internal_id]
        return str(entity_internal_id)

    async def upsert(self, *, entity_id: str, provider: str, hub_account_id: str) -> FakeBinding:
        for b in self.bindings.values():
            if b.hub_account_id == hub_account_id:
                return b
        binding = FakeBinding(
            binding_id=f"binding-{self._next_id}",
            entity_id=entity_id,
            provider=provider,
            hub_account_id=hub_account_id,
        )
        self._next_id += 1
        self.bindings[binding.id] = binding
        return binding

    async def get_by_account(self, hub_account_id: str) -> FakeBinding | None:
        for b in self.bindings.values():
            if b.hub_account_id == hub_account_id:
                return b
        return None

    async def list_for(self, entity_id: str) -> list[FakeBinding]:
        return [b for b in self.bindings.values() if b.entity_id == entity_id]

    async def list_all_active(self) -> list[FakeBinding]:
        return [b for b in self.bindings.values() if b.sync_status == "active"]

    async def update_state(
        self,
        binding: FakeBinding,
        *,
        metadata: dict | None = None,
        last_synced_at: object | None = None,
        error: str | None = None,
        status: str | None = None,
    ) -> None:
        if metadata is not None:
            binding.sync_metadata = metadata
        if error is not None:
            binding.error_message = error
        if status is not None:
            binding.sync_status = status

    async def delete(self, binding_id: str) -> None:
        self.bindings.pop(str(binding_id), None)


def patch_binding_store(monkeypatch, store: FakeBindingStore) -> None:
    """Route adapter/binding_store calls to the in-memory store."""
    import emerald.sources.binding_store as bs

    monkeypatch.setattr(bs, "upsert_binding", store.upsert)
    monkeypatch.setattr(bs, "get_binding_by_account", store.get_by_account)
    monkeypatch.setattr(bs, "get_entity_external_id", store.get_entity_external_id)
    monkeypatch.setattr(bs, "list_bindings", store.list_for)
    monkeypatch.setattr(bs, "list_all_bindings", store.list_all_active)
    monkeypatch.setattr(bs, "update_sync_state", store.update_state)
    monkeypatch.setattr(bs, "delete_binding", store.delete)
