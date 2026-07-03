"""Route completeness test: verify all expected v1 endpoints are registered.

This was originally a v2 parity test; now that v2 routes have been removed,
it verifies that the v1 API surface is complete.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="module")
def v1_paths():
    from emerald.api.app import create_app

    app = create_app()
    return {r.path for r in app.routes if hasattr(r, "path") and r.path.startswith("/v1/") and r.path != "/v1/metrics"}


REQUIRED_V1_ENDPOINTS = [
    # Memories
    "/v1/memories",
    "/v1/memories/batch",
    "/v1/memories/{memory_id}",
    "/v1/memories/{memory_id}/validate",
    # Search
    "/v1/search",
    # Profiles
    "/v1/profiles/{entity_id}",
    "/v1/profiles/{entity_id}/config",
    "/v1/profiles/{entity_id}/memory.md",
    # Upload
    "/v1/upload",
    "/v1/files",
    # Pipelines
    "/v1/pipelines/{pipeline_id}",
    # Sessions
    "/v1/sessions",
    "/v1/sessions/verify",
    # Conflicts
    "/v1/conflicts/{conflict_id}/resolve",
    # Connectors
    "/v1/connectors/{provider}",
    "/v1/connectors/{provider}/connect",
    "/v1/connectors/{provider}/callback",
    "/v1/connectors/{provider}/webhook",
    # System
    "/v1/health",
    "/v1/memories/graph",
]


def test_all_required_endpoints_present(v1_paths):
    """Every required v1 endpoint must be registered."""
    missing = set(REQUIRED_V1_ENDPOINTS) - v1_paths
    extra = v1_paths - set(REQUIRED_V1_ENDPOINTS)

    assert not missing, f"Missing v1 endpoints: {sorted(missing)}"
    # Extra endpoints are fine (e.g. GET variants of POST endpoints)


def test_no_v2_routes_leaked(v1_paths):
    """v2 routes must not be registered."""
    v2_paths = {p for p in v1_paths if "/v2/" in p}
    assert not v2_paths, f"v2 routes leaked: {v2_paths}"


def test_sessions_present(v1_paths):
    assert "/v1/sessions" in v1_paths
    assert "/v1/sessions/verify" in v1_paths


def test_conflicts_present(v1_paths):
    assert "/v1/conflicts/{conflict_id}/resolve" in v1_paths
