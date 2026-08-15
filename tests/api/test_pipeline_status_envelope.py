"""Tests for GET /v1/pipelines/{id} response envelope.

Regression: the route declared ``response_model=PipelineStatusResponse``
(top-level fields) while returning a ``{data, meta}`` envelope — every hit
on an existing job raised ResponseValidationError → 500. Found during the
:80 single-origin smoke (issue #52, 2026-08-15); the endpoint backs the
web upload pipeline polling (D2).

The session layer is mocked at the route module level (repo convention —
see tests/api/test_keys.py).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Request
from fastapi.testclient import TestClient

from emerald.api.app import create_app
from emerald.api.dependencies import api_key_auth, rate_limit


def _make_client() -> TestClient:
    async def _auth(request: Request):
        request.state.entity_id = str(uuid.uuid4())
        request.state.api_key_id = "key_test"
        request.state.permissions = ["read", "write"]
        return "authenticated"

    async def _bypass_rate(request: Request):
        return None

    app = create_app()
    app.dependency_overrides[api_key_auth] = _auth
    app.dependency_overrides[rate_limit] = _bypass_rate
    return TestClient(app)


def _mock_session(job: SimpleNamespace | None) -> MagicMock:
    """session_factory mock whose session.execute returns the job (or none)."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = job
    session_ctx = AsyncMock()
    session_ctx.__aenter__ = AsyncMock(return_value=MagicMock(execute=AsyncMock(return_value=result)))
    factory = MagicMock()
    factory.session.return_value = session_ctx
    return factory


def _job(**overrides) -> SimpleNamespace:
    base = dict(
        id=uuid.uuid4(),
        status="done",
        document_id=uuid.uuid4(),
        content_type="text/plain",
        error_message=None,
        fact_extraction_status="success",
        memory_count=3,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_pipeline_status_returns_envelope_not_500():
    """The regression: an existing job must serialize through the envelope
    (data.pipeline_id / data.status), not blow up in response validation."""
    client = _make_client()
    job = _job()
    with patch(
        "emerald.api.routes.v1.pipelines.session_factory", _mock_session(job)
    ):
        res = client.get(f"/v1/pipelines/{job.id}")

    assert res.status_code == 200
    body = res.json()
    assert body["data"]["pipeline_id"] == str(job.id)
    assert body["data"]["status"] == "done"
    assert body["data"]["memory_count"] == 3
    assert "meta" in body


def test_pipeline_status_running_fields():
    client = _make_client()
    job = _job(status="embedding", memory_count=0, fact_extraction_status=None)
    with patch(
        "emerald.api.routes.v1.pipelines.session_factory", _mock_session(job)
    ):
        res = client.get(f"/v1/pipelines/{job.id}")

    assert res.status_code == 200
    assert res.json()["data"]["status"] == "embedding"
    assert res.json()["data"]["memory_count"] == 0


def test_pipeline_status_not_found():
    client = _make_client()
    with patch(
        "emerald.api.routes.v1.pipelines.session_factory", _mock_session(None)
    ):
        res = client.get(f"/v1/pipelines/{uuid.uuid4()}")

    assert res.status_code == 404
