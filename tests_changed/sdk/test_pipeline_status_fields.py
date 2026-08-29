"""Tests for pipeline_status surface fields (P1.2b fix).

P1.2b fix: SDK docs claimed ``PipelineStatus.fact_extraction_status`` and
``PipelineStatus.memory_count`` exist, but the dataclass, the REST route,
and the DB model were all missing them.

These tests pin down:
- The SDK dataclass has the new fields.
- The SDK parses them from the route response.
- The DB model has the columns (so future migrations don't drop them).
- The Alembic migration 007 adds the columns.
- The /v1/pipelines/{id} route response includes the new fields.
"""

from __future__ import annotations

import dataclasses
import inspect
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_pipeline_status_dataclass_has_fact_extraction_status():
    from emerald.sdk.models import PipelineStatus
    fields = {f.name for f in dataclasses.fields(PipelineStatus)}
    assert "fact_extraction_status" in fields, (
        f"PipelineStatus must have fact_extraction_status (per sdk-guide.md). "
        f"Current fields: {fields}"
    )
    assert "memory_count" in fields, (
        f"PipelineStatus must have memory_count (per sdk-guide.md). "
        f"Current fields: {fields}"
    )


def test_pipeline_route_returns_new_fields():
    """The /v1/pipelines/{id} response must include fact_extraction_status + memory_count.

    2026-08-15: route response_model switched to PipelineStatusEnvelope
    ({data: PipelineStatusResponse, meta}) — resolve through components
    schemas instead of scanning the operation dict for field names."""
    sys.path.insert(0, str(REPO_ROOT))
    from emerald.api.app import create_app
    app = create_app()
    schema = app.openapi()

    # Find the operation for GET /v1/pipelines/{pipeline_id}
    op = schema["paths"]["/v1/pipelines/{pipeline_id}"]["get"]
    spec_text = str(op)
    assert (
        "PipelineStatusEnvelope" in spec_text
        or "fact_extraction_status" in spec_text
        or "PipelineStatusResponse" in spec_text
    ), "GET /v1/pipelines/{id} schema missing pipeline status schema reference"

    # The envelope's data payload (PipelineStatusResponse) must carry the
    # P1.2b fields — resolved via components, not string-scanned.
    components = schema["components"]["schemas"]
    assert "PipelineStatusEnvelope" in components, (
        "Envelope schema missing from components"
    )
    data_ref = components["PipelineStatusEnvelope"]["properties"]["data"]
    ref_name = data_ref.get("$ref", "").split("/")[-1] or data_ref.get("allOf", [{}])[0].get("$ref", "").split("/")[-1]
    assert ref_name, "Envelope data must reference PipelineStatusResponse"
    data_props = components[ref_name].get("properties", {})
    assert "fact_extraction_status" in data_props, (
        f"{ref_name} missing fact_extraction_status"
    )
    assert "memory_count" in data_props, f"{ref_name} missing memory_count"

    # And the route source must still populate the fields in the response.
    import importlib
    routes_module = importlib.import_module("emerald.api.routes.v1.pipelines")
    src = inspect.getsource(routes_module)
    assert "fact_extraction_status" in src, (
        "Route source must include fact_extraction_status in the response"
    )
    assert "memory_count" in src, (
        "Route source must include memory_count in the response"
    )


def test_pipeline_job_model_has_new_columns():
    """PipelineJob ORM model must declare the new columns."""
    sys.path.insert(0, str(REPO_ROOT))
    from sqlalchemy import inspect as sqla_inspect

    from emerald.models.pipeline_job import PipelineJob

    mapper = sqla_inspect(PipelineJob)
    column_names = {c.key for c in mapper.columns}
    assert "fact_extraction_status" in column_names, (
        f"PipelineJob must have fact_extraction_status column. "
        f"Current columns: {sorted(column_names)}"
    )
    assert "memory_count" in column_names, (
        f"PipelineJob must have memory_count column. "
        f"Current columns: {sorted(column_names)}"
    )


def test_alembic_migration_007_exists():
    """The Alembic migration adding the new columns must exist."""
    migration_path = (
        REPO_ROOT
        / "migrations" / "alembic" / "versions"
        / "007_add_pipeline_fact_extraction_status.py"
    )
    assert migration_path.exists(), (
        f"Migration file missing: {migration_path}"
    )
    text = migration_path.read_text()
    assert "fact_extraction_status" in text
    assert "memory_count" in text
    # Must declare down_revision pointing to the previous migration
    assert "down_revision" in text


def test_sdk_pipeline_status_parses_new_fields():
    """The SDK must read fact_extraction_status + memory_count from the response."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from emerald.sdk import EmeraldClient

    client = EmeraldClient(api_key="em_test", base_url="http://test")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "pipeline_id": "pipe_xyz",
            "status": "done",
            "content_type": "pdf",
            "chunk_count": 5,
            "fact_extraction_status": "success",
            "memory_count": 12,
            "document_id": None,
            "error_message": None,
        }
    }
    mock_response.raise_for_status = MagicMock()

    with patch.object(client, "_get_client") as get_client:
        mock_http = AsyncMock()
        mock_http.request = AsyncMock(return_value=mock_response)
        get_client.return_value = mock_http
        result = asyncio.run(client.pipeline_status("pipe_xyz"))

    assert result.fact_extraction_status == "success"
    assert result.memory_count == 12
