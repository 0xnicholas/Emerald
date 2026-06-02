"""Unit tests for health check endpoint."""

import pytest
from unittest.mock import AsyncMock, patch

from emerald.api.routes.v1.system import health_check


@pytest.mark.asyncio
async def test_health_all_ok():
    with patch(
        "emerald.api.routes.v1.system._probe_postgres", new_callable=AsyncMock
    ) as pg, patch(
        "emerald.api.routes.v1.system._probe_neo4j", new_callable=AsyncMock
    ) as neo, patch(
        "emerald.api.routes.v1.system._probe_redis", new_callable=AsyncMock
    ) as redis, patch(
        "emerald.api.routes.v1.system._probe_minio", new_callable=AsyncMock
    ) as minio:
        result = await health_check()

    assert result["status"] == "ok"
    assert result["checks"]["database"] == "ok"
    assert result["checks"]["neo4j"] == "ok"
    assert result["checks"]["redis"] == "ok"
    assert result["checks"]["minio"] == "ok"


@pytest.mark.asyncio
async def test_health_degraded_when_neo4j_down():
    with patch(
        "emerald.api.routes.v1.system._probe_postgres", new_callable=AsyncMock
    ), patch(
        "emerald.api.routes.v1.system._probe_neo4j", side_effect=ConnectionError("Neo4j down")
    ), patch(
        "emerald.api.routes.v1.system._probe_redis", new_callable=AsyncMock
    ), patch(
        "emerald.api.routes.v1.system._probe_minio", new_callable=AsyncMock
    ):
        result = await health_check()

    assert result["status"] == "degraded"
    assert "error" in result["checks"]["neo4j"]
