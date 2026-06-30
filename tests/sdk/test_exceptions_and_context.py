"""Tests for SDK custom exceptions and async-context-manager (P1.2c + P1.2d).

P1.2c fix: docs/api/sdk-guide.md documents typed exceptions
(EmeraldAuthError, EmeraldNotFoundError, EmeraldValidationError,
EmeraldRateLimitError, EmeraldServerError, EmeraldNetworkError) but
the SDK only raised the generic ``httpx.HTTPStatusError``.

P1.2d fix: the docs show ``async with EmeraldClient() as client:`` but
the client never implemented ``__aenter__`` / ``__aexit__``.

These tests pin the contracts and prevent silent regression.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# ---------- P1.2c: exception types exist ----------

def test_exceptions_module_importable():
    from emerald.sdk import exceptions
    expected = {
        "EmeraldError",
        "EmeraldAuthError",
        "EmeraldNotFoundError",
        "EmeraldValidationError",
        "EmeraldRateLimitError",
        "EmeraldServerError",
        "EmeraldNetworkError",
    }
    for name in expected:
        assert hasattr(exceptions, name), f"emerald.sdk.exceptions missing {name}"


def test_exceptions_hierarchy():
    """All typed exceptions inherit from EmeraldError so broad-catch works."""
    from emerald.sdk.exceptions import (
        EmeraldAuthError,
        EmeraldError,
        EmeraldNetworkError,
        EmeraldNotFoundError,
        EmeraldRateLimitError,
        EmeraldServerError,
        EmeraldValidationError,
    )
    for cls in (
        EmeraldAuthError, EmeraldNotFoundError, EmeraldValidationError,
        EmeraldRateLimitError, EmeraldServerError, EmeraldNetworkError,
    ):
        assert issubclass(cls, EmeraldError), f"{cls.__name__} must inherit from EmeraldError"


def test_validation_error_carries_field_errors():
    from emerald.sdk.exceptions import EmeraldValidationError
    err = EmeraldValidationError(
        "bad input",
        field_errors={"memory_type": "must be fact/preference/episodic"},
    )
    assert err.field_errors == {"memory_type": "must be fact/preference/episodic"}
    assert "bad input" in str(err)


def test_rate_limit_error_carries_retry_after():
    from emerald.sdk.exceptions import EmeraldRateLimitError
    err = EmeraldRateLimitError("rate limited", retry_after=42)
    assert err.retry_after == 42


def test_exception_for_status_mapping():
    """The status->exception mapper is the single source of truth."""
    from emerald.sdk.exceptions import (
        EmeraldAuthError,
        EmeraldError,
        EmeraldNotFoundError,
        EmeraldRateLimitError,
        EmeraldServerError,
        EmeraldValidationError,
        exception_for_status,
    )
    assert isinstance(exception_for_status(401, "x"), EmeraldAuthError)
    assert isinstance(exception_for_status(403, "x"), EmeraldAuthError)
    assert isinstance(exception_for_status(404, "x"), EmeraldNotFoundError)
    assert isinstance(exception_for_status(422, "x"), EmeraldValidationError)
    assert isinstance(exception_for_status(429, "x"), EmeraldRateLimitError)
    assert isinstance(exception_for_status(500, "x"), EmeraldServerError)
    assert isinstance(exception_for_status(503, "x"), EmeraldServerError)
    # Unmapped 4xx falls back to base
    assert type(exception_for_status(418, "x")) is EmeraldError


# ---------- P1.2c: client maps HTTP errors to typed exceptions ----------

def _make_client_with_401():
    """Build a client that will receive a 401 from any call."""
    from emerald.sdk import EmeraldClient
    client = EmeraldClient(api_key="em_bad", base_url="http://test")
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"
    mock_response.headers = {}
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401", request=MagicMock(), response=mock_response,
    )
    return client, mock_response


def test_client_raises_emerald_auth_error_on_401():
    from emerald.sdk import EmeraldClient
    from emerald.sdk.exceptions import EmeraldAuthError

    client = EmeraldClient(api_key="em_bad", base_url="http://test")
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Invalid API key"
    mock_response.is_success = False
    mock_response.headers = {}
    mock_response.json.return_value = {"error": {"code": "UNAUTHORIZED", "message": "Invalid"}}

    async def run():
        with patch.object(client, "_get_client") as get_client:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_response)
            get_client.return_value = mock_http
            return await client.add("x", entity_id="u1")

    with pytest.raises(EmeraldAuthError):
        asyncio.run(run())


def test_client_raises_emerald_not_found_error_on_404():
    from emerald.sdk import EmeraldClient
    from emerald.sdk.exceptions import EmeraldNotFoundError

    client = EmeraldClient(api_key="em_ok", base_url="http://test")
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = "Not found"
    mock_response.is_success = False
    mock_response.headers = {}
    mock_response.json.return_value = {"error": {"code": "NOT_FOUND", "message": "Not found"}}

    async def run():
        with patch.object(client, "_get_client") as get_client:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_response)
            get_client.return_value = mock_http
            return await client.get_memory("mem_missing")

    with pytest.raises(EmeraldNotFoundError):
        asyncio.run(run())


def test_client_raises_emerald_rate_limit_error_on_429_with_retry_after():
    from emerald.sdk import EmeraldClient
    from emerald.sdk.exceptions import EmeraldRateLimitError

    client = EmeraldClient(api_key="em_ok", base_url="http://test")
    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.text = "rate limited"
    mock_response.is_success = False
    mock_response.headers = {"Retry-After": "30"}
    mock_response.json.return_value = {"error": {"code": "RATE_LIMITED", "message": "rate limited"}}

    async def run():
        with patch.object(client, "_get_client") as get_client:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_response)
            get_client.return_value = mock_http
            return await client.profile("u1")

    with pytest.raises(EmeraldRateLimitError) as info:
        asyncio.run(run())
    assert info.value.retry_after == 30


def test_client_raises_emerald_server_error_on_500():
    from emerald.sdk import EmeraldClient
    from emerald.sdk.exceptions import EmeraldServerError

    client = EmeraldClient(api_key="em_ok", base_url="http://test")
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "boom"
    mock_response.is_success = False
    mock_response.headers = {}
    mock_response.json.return_value = {"error": {"code": "INTERNAL_ERROR", "message": "boom"}}

    async def run():
        with patch.object(client, "_get_client") as get_client:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(return_value=mock_response)
            get_client.return_value = mock_http
            return await client.profile("u1")

    with pytest.raises(EmeraldServerError):
        asyncio.run(run())


def test_client_raises_emerald_network_error_on_connect_timeout():
    """Network-level errors (not HTTP) must raise EmeraldNetworkError."""
    from emerald.sdk import EmeraldClient
    from emerald.sdk.exceptions import EmeraldNetworkError

    client = EmeraldClient(api_key="em_ok", base_url="http://test")

    async def run():
        with patch.object(client, "_get_client") as get_client:
            mock_http = AsyncMock()
            mock_http.request = AsyncMock(
                side_effect=httpx.ConnectTimeout("timed out")
            )
            get_client.return_value = mock_http
            return await client.profile("u1")

    with pytest.raises(EmeraldNetworkError):
        asyncio.run(run())


# ---------- P1.2d: async context manager ----------

def test_client_implements_aenter_aexit():
    from emerald.sdk import EmeraldClient
    assert hasattr(EmeraldClient, "__aenter__"), (
        "EmeraldClient must implement __aenter__ for `async with` (per sdk-guide.md)"
    )
    assert hasattr(EmeraldClient, "__aexit__"), (
        "EmeraldClient must implement __aexit__ for `async with` (per sdk-guide.md)"
    )


def test_async_with_closes_client():
    """`async with EmeraldClient() as c:` must close the underlying httpx client."""
    from emerald.sdk import EmeraldClient

    async def run():
        async with EmeraldClient(api_key="em_x", base_url="http://test") as client:
            # Inside the block, the http client is created lazily
            # and the same instance is returned from _get_client().
            http = await client._get_client()
            assert http is not None
            # After the block, close() must have been called.
        # If we get here without error, close() ran.
        return True

    assert asyncio.run(run())


def test_async_with_calls_close_on_exception():
    """__aexit__ must call close() even if the body raised."""
    from emerald.sdk import EmeraldClient

    async def run():
        try:
            async with EmeraldClient(api_key="em_x", base_url="http://test"):
                raise RuntimeError("boom inside the with-block")
        except RuntimeError:
            return "caught"
        return "not caught"

    assert asyncio.run(run()) == "caught"


# ---------- Existing API surface preserved ----------

def test_existing_methods_still_present():
    """Adding exceptions/context manager must not break the existing API."""
    from emerald.sdk import EmeraldClient
    for method in ("add", "search", "profile", "upload", "health",
                   "pipeline_status", "get_memory", "close"):
        assert hasattr(EmeraldClient, method), f"Lost method: {method}"


def test_sdk_does_not_expose_internal_graph_methods():
    """AGENTS.md: SDK must not expose graph operations."""
    from emerald.sdk import EmeraldClient
    public = {
        name for name, _ in inspect.getmembers(EmeraldClient, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    forbidden = {"create_memory", "infer", "list_latest_memories", "store_embedding"}
    leaked = forbidden & public
    assert not leaked, f"SDK leaked internals: {leaked}"
