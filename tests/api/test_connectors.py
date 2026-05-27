"""Tests for connector API routes."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from emerald.api.app import create_app


@pytest.fixture
def client():
    from fastapi import Request
    from emerald.api.dependencies import api_key_auth, require_write_permission, rate_limit

    async def _bypass_auth(request: Request):
        request.state.entity_id = "550e8400-e29b-41d4-a716-446655440000"
        return "authenticated"

    async def _bypass_write(request: Request):
        return "authorized"

    async def _bypass_rate(request: Request):
        return None

    app = create_app()
    app.dependency_overrides[api_key_auth] = _bypass_auth
    app.dependency_overrides[require_write_permission] = _bypass_write
    app.dependency_overrides[rate_limit] = _bypass_rate
    return TestClient(app, headers={"Authorization": "Bearer em_test"})


def test_connect_unknown_provider(client):
    response = client.post("/v1/connectors/invalid/connect")
    assert response.status_code == 400


def test_get_connector_status_not_connected(client):
    with patch("emerald.api.routes.connectors.session_factory") as mock_factory:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        mock_factory.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.session.return_value.__aexit__ = AsyncMock(return_value=False)

        response = client.get("/v1/connectors/github")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["sync_status"] == "inactive"


def test_revoke_connector_not_found(client):
    with patch("emerald.api.routes.connectors.session_factory") as mock_factory:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        mock_factory.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.session.return_value.__aexit__ = AsyncMock(return_value=False)

        response = client.delete("/v1/connectors/github")
    assert response.status_code == 204
