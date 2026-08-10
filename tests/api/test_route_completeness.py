"""Route completeness test: verify all expected v1 endpoints are registered.

This was originally a v2 parity test; now that v2 routes have been removed,
it verifies that the v1 API surface is complete.

Starlette 1.x note: ``include_router`` registers lazy ``_IncludedRouter``
objects (no ``path`` attribute) instead of concrete routes, so a simple
``app.routes`` filter yields nothing. The enumeration below recursively
expands included routers via their ``effective_candidates()`` so the real
route surface is visible.

Both app forms are covered: the stub app (no engine) and the full app
(engine injected).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


def _build_engine():
    from emerald.core.chunker import ChunkerRegistry
    from emerald.core.embedder import MockEmbeddingProvider
    from emerald.core.engine import MemoryEngine
    from emerald.core.extractor import ExtractorRegistry
    from emerald.core.graph import GraphStore
    from emerald.core.vector import VectorStore
    from emerald.pipeline.chunking.text import TextChunker
    from emerald.pipeline.extraction.text import TextExtractor

    extractors = ExtractorRegistry()
    extractors.register("text", TextExtractor())
    chunkers = ChunkerRegistry()
    chunkers.register("text", TextChunker())
    return MemoryEngine(
        extractor_registry=extractors,
        chunker_registry=chunkers,
        embedder=MockEmbeddingProvider(dimension=128),
        graph=GraphStore(use_db=False),
        vector=VectorStore(use_db=False),
        use_db=False,
    )


def _flatten_paths(routes) -> set[str]:
    """Recursively collect route paths, expanding lazy included routers."""
    paths: set[str] = set()
    for route in routes:
        path = getattr(route, "path", None)
        if path:
            paths.add(path)
        # Starlette 1.x lazy router: expand effective candidates recursively.
        candidates = getattr(route, "effective_candidates", None)
        if candidates is not None:
            paths |= _flatten_paths(candidates())
            continue
        nested = getattr(route, "routes", None)
        if nested:
            paths |= _flatten_paths(nested)
    return paths


@pytest.fixture(scope="module", params=["stub", "engine"])
def app_paths(request):
    """All registered route paths for both the stub and engine-backed app."""
    from emerald.api.app import create_app

    app = (
        create_app(engine=_build_engine())
        if request.param == "engine"
        else create_app()
    )
    return _flatten_paths(app.routes)


def _v1_paths(app_paths: set[str]) -> set[str]:
    """v1 API paths (excluding the infrastructure /v1/metrics endpoint)."""
    return {p for p in app_paths if p.startswith("/v1/") and p != "/v1/metrics"}


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


def test_all_required_endpoints_present(app_paths):
    """Every required v1 endpoint must be registered."""
    v1_paths = _v1_paths(app_paths)
    missing = set(REQUIRED_V1_ENDPOINTS) - v1_paths
    extra = v1_paths - set(REQUIRED_V1_ENDPOINTS)

    assert not missing, f"Missing v1 endpoints: {sorted(missing)}"
    # Extra endpoints are fine (e.g. GET variants of POST endpoints)
    assert extra == {
        "/v1/extract-url",
        "/v1/sources",
        "/v1/sources/connect",
        "/v1/sources/refresh",
        "/v1/sources/webhook",
        "/v1/sources/{binding_id}",
        "/v1/spaces",
        "/v1/spaces/{container_tag}",
    }, f"Unexpected extra v1 endpoints: {sorted(extra)}"


def test_no_v2_routes_leaked(app_paths):
    """v2 routes must not be registered."""
    v2_paths = {p for p in app_paths if p.startswith("/v2/")}
    assert not v2_paths, f"v2 routes leaked: {v2_paths}"


def test_sessions_present(app_paths):
    v1_paths = _v1_paths(app_paths)
    assert "/v1/sessions" in v1_paths
    assert "/v1/sessions/verify" in v1_paths


def test_conflicts_present(app_paths):
    v1_paths = _v1_paths(app_paths)
    assert "/v1/conflicts/{conflict_id}/resolve" in v1_paths
