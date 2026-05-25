"""Tests for Emerald REST API."""

import pytest
from fastapi.testclient import TestClient

from emerald.api.app import create_app
from emerald.core.chunker import ChunkerRegistry
from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.engine import MemoryEngine
from emerald.core.extractor import ExtractorRegistry
from emerald.core.graph import GraphStore
from emerald.core.vector import VectorStore
from emerald.pipeline.chunking.text import TextChunker
from emerald.pipeline.extraction.text import TextExtractor


@pytest.fixture
def engine():
    """In-memory engine shared across API tests."""
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
    """FastAPI TestClient with in-memory engine."""
    app = create_app(engine=engine)
    return TestClient(app)


# ---- Health check ----

def test_health_check(client):
    response = client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "checks" in data


# ---- Add memory ----

def test_add_text_memory(client):
    response = client.post(
        "/v1/memories",
        json={
            "content": "用户喜欢 TypeScript",
            "entity_id": "user_123",
            "content_type": "text",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert len(data["data"]["memory_ids"]) > 0
    assert data["data"]["pipeline_status"] == "done"


def test_add_memory_missing_entity_id(client):
    response = client.post(
        "/v1/memories",
        json={"content": "test"},
    )
    assert response.status_code == 422  # Validation error


# ---- Search ----

def test_search_memory(client):
    # Add first
    client.post(
        "/v1/memories",
        json={"content": "用户喜欢 TypeScript", "entity_id": "user_123"},
    )

    response = client.post(
        "/v1/search",
        json={"q": "TypeScript", "entity_id": "user_123", "search_mode": "memory"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert len(data["data"]["results"]) > 0


def test_search_unknown_entity_returns_empty(client):
    response = client.post(
        "/v1/search",
        json={"q": "anything", "entity_id": "nonexistent", "search_mode": "memory"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["data"]["results"] == []


# ---- Profile ----

def test_get_profile(client):
    client.post(
        "/v1/memories",
        json={"content": "用户是资深前端工程师", "entity_id": "user_123"},
    )

    response = client.get("/v1/profiles/user_123")
    assert response.status_code == 200
    data = response.json()
    assert data["data"]["entity_id"] == "user_123"
    assert data["data"]["memory_count"] >= 1


def test_get_profile_empty_entity(client):
    response = client.get("/v1/profiles/unknown_entity")
    assert response.status_code == 200
    data = response.json()
    assert data["data"]["entity_id"] == "unknown_entity"
    assert data["data"]["memory_count"] == 0


# ---- Unified response format ----

def test_response_has_meta(client):
    response = client.post(
        "/v1/memories",
        json={"content": "test", "entity_id": "user_123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "meta" in data
    assert "request_id" in data["meta"]


# ---- 404 handling ----

def test_404_unknown_route(client):
    response = client.get("/v1/nonexistent")
    assert response.status_code == 404
