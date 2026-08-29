"""Tests for JWT session tokens."""

import pytest

from emerald.core.session import SessionManager


@pytest.fixture
def manager():
    return SessionManager(secret="test-secret")


def test_create_and_decode_token(manager):
    """A created token can be decoded and contains the expected claims."""
    token = manager.create_token(
        "user_123",
        project_id="proj_456",
        session_id="sess_789",
        ttl_hours=1,
    )
    claims = manager.decode_token(token)

    assert claims["entity_id"] == "user_123"
    assert claims["project_id"] == "proj_456"
    assert claims["session_id"] == "sess_789"
    assert claims["iss"] == "emerald"


def test_expired_token_raises(manager):
    """Expired tokens are rejected."""
    token = manager.create_token("user_123", ttl_hours=-1)
    with pytest.raises(ValueError, match="expired"):
        manager.decode_token(token)


def test_invalid_token_raises(manager):
    """Tampered tokens are rejected."""
    with pytest.raises(ValueError):
        manager.decode_token("not.a.token")
