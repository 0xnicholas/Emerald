"""End-to-end test against full Docker Compose stack."""

import pytest


@pytest.mark.skip(reason="Requires docker compose up")
async def test_full_docker_e2e():
    """
    1. Seed dev API key.
    2. Add text memory → verify Neo4j + pgvector.
    3. Search with semantic mismatch → verify real embedding recall.
    4. Get profile → verify Redis cache hit on second call.
    5. Upload PDF → verify MinIO object, pipeline completion, searchability.
    6. Verify entity isolation.
    """
    pass
