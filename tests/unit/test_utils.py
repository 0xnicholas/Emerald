"""Tests for shared utilities."""

import uuid

import pytest

from emerald.utils import _is_uuid


@pytest.mark.parametrize("value,expected", [
    ("550e8400-e29b-41d4-a716-446655440000", True),
    (str(uuid.uuid4()), True),
    ("not-a-uuid", False),
    ("", False),
    ("12345", False),
])
def test_is_uuid(value, expected):
    assert _is_uuid(value) is expected
