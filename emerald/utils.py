"""Shared utility functions."""

from __future__ import annotations

import uuid


def _is_uuid(s: str) -> bool:
    """Check if a string is a valid UUID."""
    try:
        uuid.UUID(s)
        return True
    except ValueError:
        return False
