"""Regression test: v2 routes must mirror all v1 routes.

P1.1 fix: previously the v2 router registry was a strict subset of v1,
missing ``/v2/sessions/*`` and ``/v2/conflicts/*``. v2 is meant to be a
re-export of v1 (per the comment in ``emerald/api/routes/v2/__init__.py``),
so any divergence is a bug.

This test asserts that the set of v2 paths is a superset of the v1 paths
(modulo /metrics which is an infrastructure endpoint, not a public API).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="module")
def app_routes():
    from emerald.api.app import create_app
    app = create_app()
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    return {
        "v1": {p for p in paths if p.startswith("/v1/") and p != "/v1/metrics"},
        "v2": {p for p in paths if p.startswith("/v2/") and p != "/v2/metrics"},
    }


def test_v2_paths_superset_of_v1(app_routes):
    """Every v1 path must also exist under /v2/ (v2 is a re-export of v1)."""
    v1 = app_routes["v1"]
    v2 = app_routes["v2"]

    # Build the set of v1→v2 expected paths
    expected_v2 = {p.replace("/v1/", "/v2/", 1) for p in v1}
    missing_in_v2 = expected_v2 - v2

    assert not missing_in_v2, (
        f"v2 is missing re-exports of v1 routes: {sorted(missing_in_v2)}. "
        f"v2 is supposed to be a complete re-export of v1 (see v2/__init__.py)."
    )


def test_v2_sessions_present(app_routes):
    """/v2/sessions and /v2/sessions/verify must exist (P1.1 fix)."""
    assert "/v2/sessions" in app_routes["v2"]
    assert "/v2/sessions/verify" in app_routes["v2"]


def test_v2_conflicts_present(app_routes):
    """/v2/conflicts/{id}/resolve must exist (P1.1 fix)."""
    assert "/v2/conflicts/{conflict_id}/resolve" in app_routes["v2"]


def test_v1_sessions_present(app_routes):
    """Sanity: /v1/sessions endpoints are registered."""
    assert "/v1/sessions" in app_routes["v1"]
    assert "/v1/sessions/verify" in app_routes["v1"]


def test_v1_conflicts_present(app_routes):
    """Sanity: /v1/conflicts/{id}/resolve is registered."""
    assert "/v1/conflicts/{conflict_id}/resolve" in app_routes["v1"]
