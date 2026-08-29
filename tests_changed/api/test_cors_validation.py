"""Tests for CORS default and production safety (P2.2 fix).

P2.2 fix: the original code defaulted ``cors_allowed_origins`` to ``"*"``,
which is a fail-open default that allows any origin to call the API.
A passing warning was logged but the CORS middleware still accepted
arbitrary origins in production.

The fix:
- Default is empty string (no CORS headers at all).
- A wildcard ``"*"`` is REJECTED in production -- the app refuses to start.
- In development, ``"*"`` is still allowed (so local browser testing works).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_cors_default_is_empty_string(clean_settings):
    """Default value must be '' (most restrictive) so production is safe by default."""
    assert clean_settings.cors_allowed_origins == "", (
        f"cors_allowed_origins default must be '' (empty), got "
        f"{clean_settings.cors_allowed_origins!r}. A non-empty default would "
        f"make production permissive by accident."
    )


def test_cors_wildcard_rejected_in_production(clean_settings):
    """``CORS_ALLOWED_ORIGINS=*`` must fail validation in production."""
    from emerald.config import Settings
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            emerald_env="production",
            cors_allowed_origins="*",
        )
    # Check the error message mentions CORS / wildcard
    msg = str(exc_info.value)
    assert "CORS" in msg or "wildcard" in msg or "*" in msg, (
        f"ValidationError should mention CORS, got: {msg}"
    )


def test_cors_wildcard_allowed_in_development(clean_settings):
    """In development, ``*`` is permitted (for local browser testing)."""
    from emerald.config import Settings
    s = Settings(
        emerald_env="development",
        cors_allowed_origins="*",
    )
    assert s.cors_allowed_origins == "*"


def test_cors_specific_origins_allowed(clean_settings):
    """Specific origins are allowed in any environment."""
    from emerald.config import Settings
    s = Settings(
        emerald_env="production",
        cors_allowed_origins="https://app.example.com,https://admin.example.com",
    )
    assert s.cors_allowed_origins == "https://app.example.com,https://admin.example.com"


def test_cors_empty_string_allowed_in_production(clean_settings):
    """Empty string (no CORS headers) is the safe production default."""
    from emerald.config import Settings
    s = Settings(
        emerald_env="production",
        cors_allowed_origins="",
    )
    assert s.cors_allowed_origins == ""


def test_cors_wildcard_with_whitespace_rejected_in_production(clean_settings):
    """Even ``*`` with surrounding whitespace must be rejected in production."""
    from emerald.config import Settings
    with pytest.raises(ValidationError):
        Settings(
            emerald_env="production",
            cors_allowed_origins=" * ",  # leading/trailing spaces
        )
