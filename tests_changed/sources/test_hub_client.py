"""TotemHubClient tests against a mock HTTP transport.

Contract under test: Totem consumption standard §1–§8 —
Bearer auth + x-connection-id, {action, args} RPC envelope, seven-code
error vocabulary, {data, next} list envelope, x-totem-signature webhook
verification, §8.2 platform event shape.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import httpx
import pytest

from emerald.sources.hub import ConnectionHubAuthError, ConnectionHubError
from emerald.sources.totem import TotemHubClient


def _make_client(handler) -> TotemHubClient:
    transport = httpx.MockTransport(handler)
    client = TotemHubClient(
        base_url="http://totem.test",
        api_key="tt_live_actions",
        admin_key="tt_live_admin",
        tenant_id="emerald",
        webhook_secret="whsec_test",
    )
    client._client = httpx.AsyncClient(
        base_url=client._base_url,
        transport=transport,
    )
    return client


@pytest.mark.asyncio
async def test_create_connect_session_contract():
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"authorizationUrl": "https://open.feishu.cn/oauth/authorize?x=1"},
        )

    client = _make_client(handler)
    session = await client.create_connect_session(
        origin_owner_id="user_1",
        origin_owner_name="user_1",
        provider="feishu",
        metadata={"entity_id": "user_1"},
    )

    assert captured["auth"] == "Bearer tt_live_admin"
    assert captured["path"] == "/admin/tenants/emerald/oauth/start"
    # Default redirect URI derives from the base URL (totem's callback).
    assert captured["body"] == {"redirectUri": "http://totem.test/oauth/callback/feishu"}
    assert session.url == "https://open.feishu.cn/oauth/authorize?x=1"
    # Totem has no session token: session id is the tenant handle.
    assert session.id == "emerald"
    assert session.token == ""
    assert session.metadata["entity_id"] == "user_1"
    await client.aclose()


@pytest.mark.asyncio
async def test_create_connect_session_respects_redirect_uri_and_connection_id():
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"authorizationUrl": "https://auth"})

    client = _make_client(handler)
    client._oauth_redirect_uri = "https://emerald.example/cb"
    await client.create_connect_session(
        origin_owner_id="user_1",
        origin_owner_name="user_1",
        provider="feishu",
        metadata={"connection_id": "conn_7"},
    )
    assert captured["body"] == {
        "redirectUri": "https://emerald.example/cb",
        "connectionId": "conn_7",
    }
    await client.aclose()


@pytest.mark.asyncio
async def test_execute_action_contract():
    """RPC: Bearer actions key + x-connection-id + flat {action, args}."""
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        captured["connection"] = request.headers.get("x-connection-id")
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"data": [{"doc_id": "dox1", "title": "Q3", "doc_type": "docx"}], "next": None},
        )

    client = _make_client(handler)
    result = await client.execute_action(
        account_id="conn_9",
        action="search_docs",
        query={"query": " ", "limit": 50},
    )
    assert captured["auth"] == "Bearer tt_live_actions"
    assert captured["connection"] == "conn_9"
    assert captured["path"] == "/actions/rpc"
    # The five-part StackOne envelope does not exist: query/body merge into args.
    assert captured["body"] == {"action": "search_docs", "args": {"query": " ", "limit": 50}}
    assert result["data"][0]["doc_id"] == "dox1"
    await client.aclose()


@pytest.mark.asyncio
async def test_execute_action_merges_body_and_query_into_args():
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"doc_id": "dox1", "content": "# Hi"})

    client = _make_client(handler)
    await client.execute_action(
        account_id="conn_9",
        action="get_doc_content",
        body={"doc_id": "dox1"},
        query={"limit": 1},
    )
    assert captured["body"] == {
        "action": "get_doc_content",
        "args": {"doc_id": "dox1", "limit": 1},
    }
    await client.aclose()


@pytest.mark.asyncio
async def test_auth_failure_raises_hub_auth_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": "auth_expired", "message": "token expired"})

    client = _make_client(handler)
    with pytest.raises(ConnectionHubAuthError):
        await client.execute_action(account_id="c", action="search_docs")
    await client.aclose()


@pytest.mark.asyncio
async def test_forbidden_raises_hub_auth_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"code": "forbidden", "message": "not in allowlist"})

    client = _make_client(handler)
    with pytest.raises(ConnectionHubAuthError):
        await client.execute_action(account_id="c", action="search_docs")
    await client.aclose()


@pytest.mark.asyncio
async def test_rate_limited_surfaces_retry_after():
    """429 carries retryable + retryAfterSeconds; the message must expose
    them so callers can back off (standard §4)."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "code": "rate_limited",
                "message": "rate limit exceeded",
                "retryable": True,
                "retryAfterSeconds": 30,
            },
        )

    client = _make_client(handler)
    with pytest.raises(ConnectionHubError) as excinfo:
        await client.execute_action(account_id="c", action="search_docs")
    assert "rate_limited" in str(excinfo.value)
    assert "retryAfterSeconds=30" in str(excinfo.value)
    await client.aclose()


@pytest.mark.asyncio
async def test_validation_error_raises_hub_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "code": "validation_error",
                "message": "args invalid",
                "details": [{"path": "query", "keyword": "minLength", "message": "too short"}],
            },
        )

    client = _make_client(handler)
    with pytest.raises(ConnectionHubError) as excinfo:
        await client.execute_action(account_id="c", action="search_docs", query={"query": ""})
    assert "validation_error" in str(excinfo.value)
    await client.aclose()


@pytest.mark.asyncio
async def test_upstream_error_raises_hub_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"code": "upstream_error", "message": "feishu down"})

    client = _make_client(handler)
    with pytest.raises(ConnectionHubError):
        await client.execute_action(account_id="c", action="search_docs")
    await client.aclose()


@pytest.mark.asyncio
async def test_network_failure_raises_hub_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    client = _make_client(handler)
    with pytest.raises(ConnectionHubError):
        await client.execute_action(account_id="c", action="search_docs")
    await client.aclose()


@pytest.mark.asyncio
async def test_list_accounts_contract():
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        captured["path"] = request.url.path
        return httpx.Response(
            200,
            json={
                "connections": [
                    {
                        "id": "conn_1",
                        "tenant_id": "emerald",
                        "connector_id": "feishu",
                        "name": "Feishu 账号",
                        "status": "active",
                        "owner_id": "ou_user_1",
                        "created_at": "2026-08-10T10:00:00Z",
                    }
                ]
            },
        )

    client = _make_client(handler)
    accounts = await client.list_accounts("user_1")
    assert captured["auth"] == "Bearer tt_live_admin"
    assert captured["path"] == "/admin/tenants/emerald/connections"
    assert len(accounts) == 1
    assert accounts[0].id == "conn_1"
    assert accounts[0].provider == "feishu"
    assert accounts[0].origin_owner_id == "ou_user_1"
    assert accounts[0].status == "active"
    await client.aclose()


@pytest.mark.asyncio
async def test_list_accounts_empty():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"connections": []})

    client = _make_client(handler)
    accounts = await client.list_accounts("user_1")
    assert accounts == []
    await client.aclose()


@pytest.mark.asyncio
async def test_list_accounts_admin_failure_raises_hub_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"code": "not_found", "message": "tenant not found"})

    client = _make_client(handler)
    with pytest.raises(ConnectionHubError):
        await client.list_accounts("user_1")
    await client.aclose()


def _sign(raw: bytes, secret: str) -> str:
    return base64.urlsafe_b64encode(
        hmac.new(secret.encode(), raw, hashlib.sha256).digest()
    ).decode()


@pytest.mark.asyncio
async def test_verify_webhook_signature_valid():
    """Standard §8.3: HMAC-SHA256 over raw body, base64url, x-totem-signature."""
    client = _make_client(lambda req: httpx.Response(200, json={}))
    raw = b'{"event":"connection.created"}'
    headers = {"x-totem-signature": _sign(raw, "whsec_test")}
    assert await client.verify_webhook(raw, headers) is True
    await client.aclose()


@pytest.mark.asyncio
async def test_verify_webhook_rejects_tampered_body():
    client = _make_client(lambda req: httpx.Response(200, json={}))
    raw = b'{"event":"connection.created"}'
    headers = {"x-totem-signature": _sign(b'{"event":"other"}', "whsec_test")}
    assert await client.verify_webhook(raw, headers) is False
    await client.aclose()


@pytest.mark.asyncio
async def test_verify_webhook_rejects_missing_signature():
    client = _make_client(lambda req: httpx.Response(200, json={}))
    assert await client.verify_webhook(b'{"event":"x"}', {}) is False
    await client.aclose()


@pytest.mark.asyncio
async def test_verify_webhook_rejects_missing_secret():
    client = _make_client(lambda req: httpx.Response(200, json={}))
    client._webhook_secret = ""
    assert await client.verify_webhook(b'{"event":"x"}', {}) is False
    await client.aclose()


@pytest.mark.asyncio
async def test_parse_event_normalizes_standard_envelope():
    """§8.2 platform event shape: event/tenant_id/connection_id/..."""
    client = _make_client(lambda req: httpx.Response(200, json={}))
    raw = json.dumps(
        {
            "event": "connection.created",
            "tenant_id": "emerald",
            "connection_id": "conn_9",
            "record_type": "connection",
            "record_id": "conn_9",
            "provider": "feishu",
            "event_date": "2026-08-10T10:00:00Z",
            "sent_at": "2026-08-10T10:00:01Z",
        }
    ).encode()
    event = await client.parse_event(raw)
    assert event.event_type == "connection.created"
    assert event.provider == "feishu"
    assert event.account_id == "conn_9"
    assert event.origin_owner_id == "emerald"
    assert event.payload == {}
    await client.aclose()


@pytest.mark.asyncio
async def test_parse_event_tolerates_legacy_shape():
    """v1 direct-subscription period tolerates upstream-ish field names."""
    client = _make_client(lambda req: httpx.Response(200, json={}))
    raw = json.dumps(
        {
            "event": "doc.changed",
            "provider": "feishu",
            "account_id": "conn_9",
            "origin_owner_id": "emerald",
            "payload": {"doc_id": "dox1"},
        }
    ).encode()
    event = await client.parse_event(raw)
    assert event.event_type == "doc.changed"
    assert event.account_id == "conn_9"
    assert event.origin_owner_id == "emerald"
    assert event.payload == {"doc_id": "dox1"}
    await client.aclose()


@pytest.mark.asyncio
async def test_parse_event_rejects_invalid_json():
    client = _make_client(lambda req: httpx.Response(200, json={}))
    with pytest.raises(ConnectionHubError):
        await client.parse_event(b"not-json")
    await client.aclose()
