"""POST /v1/memories content-type resolution tests (spec issue #1).

The route must pass an undeclared content_type through to the engine as
None so sniffing can kick in — it must not substitute "text".
"""

from __future__ import annotations

from fastapi import Request
from fastapi.testclient import TestClient

from emerald.api.app import create_app
from emerald.api.dependencies import api_key_auth, rate_limit, require_write_permission
from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.engine import MemoryEngine
from emerald.core.graph import GraphStore
from emerald.core.vector import VectorStore


def _make_engine() -> MemoryEngine:
    """Engine with default registries + in-memory stores (no DB)."""
    return MemoryEngine(
        embedder=MockEmbeddingProvider(dimension=128),
        graph=GraphStore(use_db=False),
        vector=VectorStore(use_db=False),
        use_db=False,
    )


def _make_client() -> TestClient:
    async def _auth(request: Request):
        request.state.entity_id = "user_123"
        request.state.api_key_id = "key_test"
        request.state.permissions = ["read", "write"]
        return "authenticated"

    async def _bypass_write(request: Request):
        return "authorized"

    async def _bypass_rate(request: Request):
        return None

    app = create_app(engine=_make_engine())
    app.dependency_overrides[api_key_auth] = _auth
    app.dependency_overrides[require_write_permission] = _bypass_write
    app.dependency_overrides[rate_limit] = _bypass_rate
    return TestClient(app, headers={"Authorization": "Bearer em_test"})


def test_post_memories_without_content_type_sniffs_json():
    """An undeclared content_type must reach the engine as None and be sniffed."""
    client = _make_client()
    resp = client.post(
        "/v1/memories",
        json={"content": '{"a": 1, "b": 2}', "entity_id": "user_123"},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["pipeline_status"] == "done"
    assert len(body["memory_ids"]) == 2, "JSON must be structurally chunked"


def test_post_memories_without_content_type_sniffs_csv():
    """CSV content is sniffed through the route too."""
    client = _make_client()
    resp = client.post(
        "/v1/memories",
        json={"content": "季度,营收\nQ1,100\nQ2,150", "entity_id": "user_123"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["pipeline_status"] == "done"


def test_post_memories_explicit_text_not_sniffed():
    """Explicit content_type=text keeps text behavior through the route."""
    client = _make_client()
    resp = client.post(
        "/v1/memories",
        json={
            "content": '{"a": 1, "b": 2}',
            "entity_id": "user_123",
            "content_type": "text",
        },
    )
    assert resp.status_code == 200
    assert len(resp.json()["data"]["memory_ids"]) == 1
