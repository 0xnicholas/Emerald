"""Integration tests for auth against real PostgreSQL."""

import pytest


@pytest.mark.asyncio
async def test_valid_key_authenticates():
    # TODO: unskip after seed_dev_api_key.py runs in test setup
    pytest.skip("Requires running PostgreSQL + seeded api_keys")
