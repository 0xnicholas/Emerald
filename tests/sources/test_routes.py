"""API route tests for /v1/sources (ADR-0004 connection hub flow)."""

from __future__ import annotations

from fastapi import Request
from fastapi.testclient import TestClient

from emerald.api.app import create_app
from emerald.api.dependencies import api_key_auth, rate_limit, require_write_permission
from emerald.sources.hub import ConnectionHubError
from tests.sources.fake_hub import FakeBindingStore, FakeHub, _sign, patch_binding_store


def _make_client(monkeypatch, hub: FakeHub) -> tuple[TestClient, FakeBindingStore]:
    store = FakeBindingStore()
    patch_binding_store(monkeypatch, store)

    async def _auth(request: Request):
        request.state.api_key_id = "key_test"
        request.state.entity_id = "user_1"
        request.state.permissions = ["read", "write"]
        return "authenticated"

    async def _write(request: Request):
        return "authorized"

    async def _no_rate_limit(request: Request):
        return None

    app = create_app()
    app.dependency_overrides[api_key_auth] = _auth
    app.dependency_overrides[require_write_permission] = _write
    app.dependency_overrides[rate_limit] = _no_rate_limit

    import emerald.api.routes.v1.sources as sources_routes

    monkeypatch.setattr(sources_routes, "get_hub", lambda: hub)
    return TestClient(app, headers={"Authorization": "Bearer em_test"}), store


def test_connect_returns_auth_link(monkeypatch):
    hub = FakeHub()
    client, _ = _make_client(monkeypatch, hub)

    resp = client.post(
        "/v1/sources/connect",
        json={"entity_id": "user_1", "provider": "feishu"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["auth_link_url"].startswith("https://hub.example.com/connect")
    assert data["provider"] == "feishu"
    assert len(hub.created_sessions) == 1
    assert hub.created_sessions[0].metadata == {"entity_id": "user_1"}


def test_connect_rejects_unknown_provider(monkeypatch):
    hub = FakeHub()
    client, _ = _make_client(monkeypatch, hub)

    resp = client.post(
        "/v1/sources/connect",
        json={"entity_id": "user_1", "provider": "slack"},
    )
    assert resp.status_code == 422


def test_webhook_rejects_bad_signature(monkeypatch):
    hub = FakeHub()
    client, _ = _make_client(monkeypatch, hub)

    resp = client.post(
        "/v1/sources/webhook",
        content=b'{"event":"doc.changed"}',
        headers={"x-totem-signature": "forged"},
    )
    assert resp.status_code == 401


def test_webhook_accepts_valid_signature(monkeypatch):
    hub = FakeHub()
    hub.listings["acc_1"] = [
        {"doc_id": "dox1", "title": "notes.md", "doc_type": "docx", "updated_at": "v1"}
    ]
    hub.contents["acc_1:dox1"] = {"doc_id": "dox1", "content": "## Notes body"}

    client, store = _make_client(monkeypatch, hub)
    import asyncio

    async def _seed() -> None:
        await store.upsert(entity_id="user_1", provider="feishu", hub_account_id="acc_1")

    asyncio.run(_seed())

    # Capture ingestion instead of hitting the real pipeline (no DB in tests).
    captured: list[dict] = []

    async def _sink(*, content, content_type, entity_id, metadata=None):
        captured.append({"content": content, "entity_id": entity_id})

    import emerald.sources.adapter as adapter_mod

    monkeypatch.setattr(adapter_mod, "default_content_cb", lambda: _sink)

    body = b'{"event":"doc.changed","provider":"feishu","account_id":"acc_1","payload":{}}'
    resp = client.post(
        "/v1/sources/webhook",
        content=body,
        headers={"x-totem-signature": _sign(body, "test-secret")},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["event_type"] == "doc.changed"
    assert data["ingested"] == 1
    assert captured[0]["content"] == "## Notes body"


def test_webhook_unknown_account_returns_200_with_error(monkeypatch):
    """Deliveries for unbound accounts must not crash the endpoint."""
    hub = FakeHub()
    client, _ = _make_client(monkeypatch, hub)
    body = b'{"event":"doc.changed","provider":"feishu","account_id":"ghost","payload":{}}'
    resp = client.post(
        "/v1/sources/webhook",
        content=body,
        headers={"x-totem-signature": _sign(body, "test-secret")},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["errors"] == ["no binding for account"]


def test_list_sources_empty(monkeypatch):
    hub = FakeHub()
    client, _ = _make_client(monkeypatch, hub)

    resp = client.get("/v1/sources", params={"entity_id": "user_1"})
    assert resp.status_code == 200
    assert resp.json()["data"] == []


def test_refresh_creates_bindings_from_hub_accounts(monkeypatch):
    hub = FakeHub()
    from emerald.sources.hub import HubAccount

    hub.accounts["user_1"] = [
        HubAccount(id="acc_1", provider="feishu", origin_owner_id="user_1"),
        HubAccount(id="acc_2", provider="feishu", origin_owner_id="user_1"),
    ]
    client, _ = _make_client(monkeypatch, hub)

    resp = client.post("/v1/sources/refresh", params={"entity_id": "user_1"})
    assert resp.status_code == 200
    assert resp.json()["data"]["accounts"] == 2
    assert len(resp.json()["data"]["bindings"]) == 2

    listed = client.get("/v1/sources", params={"entity_id": "user_1"}).json()["data"]
    assert {b["provider"] for b in listed} == {"feishu"}
    assert all(b["sync_status"] == "active" for b in listed)


def test_delete_source(monkeypatch):
    hub = FakeHub()
    hub.accounts["user_1"] = []
    client, _ = _make_client(monkeypatch, hub)

    resp = client.delete(
        "/v1/sources/11111111-1111-4111-8111-111111111111",
        params={"entity_id": "user_1"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True


class _FailingHub(FakeHub):
    """Hub whose failure paths raise ConnectionHubError (502 territory)."""

    async def create_connect_session(self, **kwargs):
        raise ConnectionHubError("connect session failed")

    async def list_accounts(self, origin_owner_id: str):
        raise ConnectionHubError("accounts failed")


def test_connect_hub_failure_returns_502_not_500(monkeypatch):
    """P1-3: hub failure on connect must surface as 502, not crash to 500."""
    client, _ = _make_client(monkeypatch, _FailingHub())
    resp = client.post(
        "/v1/sources/connect",
        json={"entity_id": "user_1", "provider": "feishu"},
    )
    assert resp.status_code == 502


def test_refresh_hub_failure_returns_502_not_500(monkeypatch):
    """P1-3: hub failure on refresh must surface as 502, not crash to 500."""
    client, _ = _make_client(monkeypatch, _FailingHub())
    resp = client.post("/v1/sources/refresh", params={"entity_id": "user_1"})
    assert resp.status_code == 502
