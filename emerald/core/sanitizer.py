"""Log sanitizer for PII and sensitive data (A7).

Detects and masks common PII patterns in log messages before they are emitted.
Integrated as a structlog processor in ``emerald.core.logging``.

Enabled by default in production (``EMERALD_ENV=production``).
Disabled in development for easier debugging.

Masks:
  - Email addresses     → ``[EMAIL]``
  - Phone numbers       → ``[PHONE]``
  - API keys            → ``[API_KEY]``
  - IPv4 addresses      → ``[IP]``
  - Credit card numbers → ``[CC]``
  - SSN (US)            → ``[SSN]``
  - Bearer tokens       → ``[TOKEN]``
  - JWT tokens          → ``[JWT]``
"""

from __future__ import annotations

import re
from typing import Any

# ── PII detection patterns ────────────────────────────────────────────

_PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Most-specific first: credit cards, SSN before generic phone patterns
    # Credit card numbers (13-19 digits with separators)
    (re.compile(r"\b[3456]\d{3}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4,7}\b"), "[CC]"),
    # US SSN
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    # Email addresses
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[EMAIL]"),
    # JWT tokens (base64-encoded JSON with dots) — before generic API key
    (re.compile(r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}"), "[JWT]"),
    # Bearer tokens — before generic API key
    (re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*"), "[TOKEN]"),
    # OpenAI-style API keys (sk-...)
    (re.compile(r"sk-[a-zA-Z0-9]{32,}"), "[API_KEY]"),
    # Generic API key patterns (em_, pk_, etc.)
    (re.compile(r"\b[A-Za-z]{2,3}_[a-fA-F0-9]{32,}\b"), "[API_KEY]"),
    # IPv4 addresses — before phone (IPv4 is more specific)
    (re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"), "[IP]"),
    # Phone numbers — require leading + (international) or parenthesised area code
    # to avoid matching UUIDs, pipeline IDs, and version numbers.
    (re.compile(r"(?:\+[\d]{1,3}[-.\s]?\(?\d{2,4}\)?[-.\s]?\d{2,4}[-.\s]?\d{2,4}|\(\d{2,4}\)[-.\s]?\d{2,4}[-.\s]?\d{2,4})"), "[PHONE]"),
]

# ── Sensitive field names (exact or glob match) ────────────────────────

_SENSITIVE_FIELD_PATTERNS: list[str] = [
    "api_key",
    "apikey",
    "secret",
    "password",
    "passwd",
    "token",
    "credential",
    "private_key",
    "encryption_key",
    "*_secret",
    "*_key",
    "*_token",
    "*_password",
]

_REDACTED_VALUE = "[REDACTED]"


def _matches_sensitive_field(name: str) -> bool:
    """Check if a field name matches a sensitive pattern."""
    lower = name.lower()
    for pattern in _SENSITIVE_FIELD_PATTERNS:
        if pattern.startswith("*") and pattern.endswith("*"):
            if pattern[1:-1] in lower:
                return True
        elif pattern.startswith("*"):
            if lower.endswith(pattern[1:]):
                return True
        elif pattern.endswith("*"):
            if lower.startswith(pattern[:-1]):
                return True
        elif lower == pattern:
            return True
    return False


def sanitize_string(value: str) -> str:
    """Apply all PII patterns to a string value, replacing matches with
    their corresponding mask labels.

    Returns the sanitized string (unchanged if no PII detected).
    """
    for pattern, mask in _PII_PATTERNS:
        value = pattern.sub(mask, value)
    return value


def sanitize_event_dict(
    _logger: Any,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """structlog processor: sanitize PII from log event values.

    - Scans string values for PII patterns (email, phone, etc.)
    - Redacts values whose keys match sensitive field names
    - Recursively processes nested dicts

    Safe to call multiple times — the same field won't be masked twice
    (the replacement strings contain no PII-recognisable text).
    """
    return _sanitize_dict(event_dict)


def _sanitize_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Recursively sanitize a dict in place."""
    keys_to_redact: set[str] = set()
    for key, value in d.items():
        if _matches_sensitive_field(key):
            keys_to_redact.add(key)
            continue
        if isinstance(value, str):
            d[key] = sanitize_string(value)
        elif isinstance(value, dict):
            d[key] = _sanitize_dict(value)
        elif isinstance(value, list):
            d[key] = [
                sanitize_string(item) if isinstance(item, str) else item
                for item in value
            ]
    for key in keys_to_redact:
        d[key] = _REDACTED_VALUE
    return d
