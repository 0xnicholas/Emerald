"""Tests for API URL-path versioning.

v2 routes were removed in v0.4.0 (see CHANGELOG); the v2 route surface
is guarded by the route-completeness tests. These tests cover the v1
route surface, the 404 contract for unknown versions, and the SDK's
version configuration.
"""

from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from emerald.api.app import create_app
from emerald.api.dependencies import api_key_auth, rate_limit, require_write_permission
from emerald.core.chunker import ChunkerRegistry
from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.engine import MemoryEngine
from emerald.core.extractor import ExtractorRegistry
from emerald.core.graph import GraphStore
from emerald.core.vector import VectorStore
from emerald.pipeline.chunking.text import TextChunker
from emerald.pipeline.extraction.text import TextExtractor
from emerald.sdk.client import EmeraldClient


@pytest.fixture
def engine():
    extractors = ExtractorRegistry()
    extractors.register("text", TextExtractor())
    chunkers = ChunkerRegistry()
    chunkers.register("text", TextChunker())
    embedder = MockEmbeddingProvider(dimension=128)
    graph = GraphStore(use_db=False)
    vector = VectorStore(use_db=False)
    return MemoryEngine(
        extractor_registry=extractors,
        chunker_registry=chunkers,
        embedder=embedder,
        graph=graph,
        vector=vector,
        use_db=False,
    )


@pytest.fixture
def client(engine):
    async def _bypass_auth(request: Request):
        return "authenticated"

    async def _bypass_write(request: Request):
        return "authorized"

    async def _bypass_rate(request: Request):
        return None

    app = create_app(engine=engine)
    app.dependency_overrides[api_key_auth] = _bypass_auth
    app.dependency_overrides[require_write_permission] = _bypass_write
    app.dependency_overrides[rate_limit] = _bypass_rate
    return TestClient(app, headers={"Authorization": "Bearer em_test"})


class TestApiVersioning:
    """Verify that v1 routes are registered and functional, and unknown versions 404."""

    def test_v1_health_returns_200(self, client):
        response = client.get("/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] in ("ok", "degraded")

    def test_v2_health_returns_404(self, client):
        """GET /v2/health must 404: v2 routes were removed in v0.4.0."""
        response = client.get("/v2/health")
        assert response.status_code == 404

    def test_v1_memories_post(self, client):
        response = client.post(
            "/v1/memories",
            json={"content": "Test memory", "entity_id": "user_v1", "content_type": "text"},
        )
        assert response.status_code == 200
        assert "memory_ids" in response.json()["data"]

    def test_v2_memories_post(self, client):
        """POST /v2/memories must 404: v2 routes were removed in v0.4.0."""
        response = client.post(
            "/v2/memories",
            json={"content": "Test memory", "entity_id": "user_v2", "content_type": "text"},
        )
        assert response.status_code == 404

    def test_v1_search_post(self, client):
        client.post(
            "/v1/memories",
            json={
                "content": "Test search content",
                "entity_id": "user_search",
                "content_type": "text",
            },
        )
        response = client.post(
            "/v1/search",
            json={"q": "test", "entity_id": "user_search", "search_mode": "memory"},
        )
        assert response.status_code == 200
        assert "results" in response.json()["data"]

    def test_v2_search_post(self, client):
        """POST /v2/search must 404: v2 routes were removed in v0.4.0."""
        response = client.post(
            "/v2/search",
            json={"q": "test", "entity_id": "user_search", "search_mode": "memory"},
        )
        assert response.status_code == 404

    def test_nonexistent_version_returns_404(self, client):
        response = client.get("/v3/health")
        assert response.status_code == 404

    def test_sdk_default_version_is_v1(self):
        c = EmeraldClient(api_key="em_test", base_url="http://localhost:8000")
        assert c.api_version == "v1"

    def test_sdk_v2_version(self):
        c = EmeraldClient(api_key="em_test", base_url="http://localhost:8000", api_version="v2")
        assert c.api_version == "v2"

    def test_sdk_generates_correct_paths(self):
        c = EmeraldClient(api_key="em_test", base_url="http://localhost:8000", api_version="v2")
        assert f"/{c.api_version}/memories" == "/v2/memories"
        assert f"/{c.api_version}/search" == "/v2/search"
        assert f"/{c.api_version}/profiles/abc" == "/v2/profiles/abc"
