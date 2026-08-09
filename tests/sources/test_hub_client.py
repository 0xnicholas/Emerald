"""StackOneHubClient tests against a mock HTTP transport."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import httpx
import pytest

from emerald.sources.hub import ConnectionHubAuthError, ConnectionHubError
from emerald.sources.stackone import StackOneHubClient


def _make_client(handler) -> StackOneHubClient:
    transport = httpx.MockTransport(handler)
    client = StackOneHubClient(
        api_base_url="https://api.stackone.test",
        api_key_id="key_id",
        api_key_secret="key_secret",
        webhook_secret="whsec_test",
    )
    client._client = httpx.AsyncClient(
        base_url=client._api_base_url,
        transport=transport,
        headers=client._client.headers,
    )
    return client


def _basic_auth() -> str:
    raw = base64.b64encode(b"key_id:key_secret").decode()
    return f"Basic {raw}"


@pytest.mark.asyncio
async def test_create_connect_session_contract():
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": 42,
                "token": "tok123",
                "auth_link_url": "https://hub.example.com/connect",
                "expires_in": 1800,
                "provider": "googledrive",
            },
        )

    client = _make_client(handler)
    session = await client.create_connect_session(
        origin_owner_id="user_1",
        origin_owner_name="user_1",
        provider="googledrive",
        metadata={"entity_id": "user_1"},
    )

    assert captured["auth"] == _basic_auth()
    assert captured["body"]["origin_owner_id"] == "user_1"
    assert captured["body"]["provider"] == "googledrive"
    assert captured["body"]["metadata"] == {"entity_id": "user_1"}
    assert session.url == "https://hub.example.com/connect"
    assert session.token == "tok123"
    assert session.id == "42"
    await client.aclose()


@pytest.mark.asyncio
async def test_execute_action_contract():
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["account"] = request.headers.get("x-account-id")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": [{"id": "f1"}]})

    client = _make_client(handler)
    result = await client.execute_action(
        account_id="acc_9",
        action="list_files",
        query={"folder": "root"},
    )
    assert captured["account"] == "acc_9"
    assert captured["body"]["action"] == "list_files"
    assert captured["body"]["query"] == {"folder": "root"}
    assert result == {"results": [{"id": "f1"}]}
    await client.aclose()


@pytest.mark.asyncio
async def test_auth_failure_raises_hub_auth_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid credentials")

    client = _make_client(handler)
    with pytest.raises(ConnectionHubAuthError):
        await client.create_connect_session(
            origin_owner_id="u",
            origin_owner_name="u",
            provider="googledrive",
        )
    await client.aclose()


@pytest.mark.asyncio
async def test_server_error_raises_hub_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    client = _make_client(handler)
    with pytest.raises(ConnectionHubError):
        await client.list_accounts("u")
    await client.aclose()


def _sign(raw: bytes, secret: str) -> str:
    return base64.urlsafe_b64encode(
        hmac.new(secret.encode(), raw, hashlib.sha256).digest()
    ).decode()


@pytest.mark.asyncio
async def test_verify_webhook_signature_valid():
    client = _make_client(lambda req: httpx.Response(200, json={}))
    raw = b'{"event":"file.changed"}'
    headers = {"x-stackone-signature": _sign(raw, "whsec_test")}
    assert await client.verify_webhook(raw, headers) is True
    await client.aclose()


@pytest.mark.asyncio
async def test_verify_webhook_rejects_tampered_body():
    client = _make_client(lambda req: httpx.Response(200, json={}))
    raw = b'{"event":"file.changed"}'
    headers = {"x-stackone-signature": _sign(b'{"event":"other"}', "whsec_test")}
    assert await client.verify_webhook(raw, headers) is False
    await client.aclose()


@pytest.mark.asyncio
async def test_verify_webhook_rejects_missing_secret():
    client = _make_client(lambda req: httpx.Response(200, json={}))
    raw = b'{"event":"file.changed"}'
    # No webhook secret configured on the client
    client._webhook_secret = ""
    assert await client.verify_webhook(raw, {}) is False
    await client.aclose()


@pytest.mark.asyncio
async def test_parse_event_normalizes_envelope():
    client = _make_client(lambda req: httpx.Response(200, json={}))
    raw = json.dumps(
        {
            "event": "file.changed",
            "provider": "googledrive",
            "account_id": "acc_9",
            "origin_owner_id": "user_1",
            "payload": {"file": {"id": "f1"}},
        }
    ).encode()
    event = await client.parse_event(raw)
    assert event.event_type == "file.changed"
    assert event.provider == "googledrive"
    assert event.account_id == "acc_9"
    assert event.origin_owner_id == "user_1"
    assert event.payload == {"file": {"id": "f1"}}
    await client.aclose()
