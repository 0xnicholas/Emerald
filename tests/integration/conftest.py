"""Shared fixtures for integration tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def docker_available():
    """Return True if Docker daemon is reachable."""
    import shutil

    return shutil.which("docker") is not None
