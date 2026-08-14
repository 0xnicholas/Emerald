"""Community-forgetting quality scenario on real storage (Neo4j) — B5 T4, ticket #40.

The in-memory suite (test_community_forgetting.py) runs everywhere. This
module re-runs the exact same deterministic scenario against a real
Neo4j backend, covering the Cypher branches of the community-forgetting
flow:

- community detection adjacency via ``get_relationship_neighbors`` and
  the mention-read primitive on the Cypher branch (the corpus carries no
  mention bridges — the relationship-bridge path is the exercised one),
  with ``list_forget_candidates`` ordering (created_at DESC, id
  tie-break) — the same partition and decisions the in-memory suite
  asserts;
- ``mark_expired`` on the Cypher path: is_latest=False + reason
  ``community_forgotten``, atomic edge/mention cleanup;
- ``ProfileManager.compute`` over ``list_latest_memories`` (Cypher) —
  the profile-referenced signal community is exempt on real storage too;
- retrieval through SearchOrchestrator: vector search + ``get_memory``
  Cypher reads with is_latest filtering — the same precise pre/post
  retrieval-set assertions as the in-memory suite.

Skipped when no test Neo4j is reachable (skip, not fail); the CI
`quality-temporal` job runs it with the compose service up, so the
aggregate gate covers both backends.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.graph import GraphStore
from emerald.core.vector import VectorStore
from tests.quality.communities.scenario import (
    make_orchestrator,
    run_community_forgetting,
    seed_community_corpus,
)

pytestmark = [pytest.mark.quality]


async def _clean_entity(driver, entity: str) -> None:
    """Remove an entity's memories, mentions and entity node (clean slate)."""
    async with driver.session() as session:
        await session.run(
            "MATCH (m:Memory) WHERE m.entity_id = $e DETACH DELETE m",
            e=entity,
        )
        await session.run(
            "MATCH (mn:Mention) WHERE mn.entity_id = $e DETACH DELETE mn",
            e=entity,
        )
        await session.run(
            "MATCH (e:Entity) WHERE e.id = $e DETACH DELETE e",
            e=entity,
        )


async def _backdate_neo4j(driver, memory_id: str, days: int) -> None:
    """Rewind created_at on the real store (Cypher path)."""
    stamp = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    async with driver.session() as session:
        await session.run(
            "MATCH (m:Memory {id: $id}) SET m.created_at = datetime($stamp)",
            id=memory_id,
            stamp=stamp,
        )


@pytest.mark.asyncio
async def test_community_forgetting_on_neo4j(neo4j_driver) -> None:
    """The community-forgetting scenario holds on a real Neo4j backend."""
    store = GraphStore(use_db=True)
    vector = VectorStore(use_db=False)
    embedder = MockEmbeddingProvider(dimension=128)
    entity_id = f"user_quality_community_neo4j_{uuid.uuid4().hex[:8]}"
    await _clean_entity(neo4j_driver, entity_id)

    corpus = await seed_community_corpus(
        store,
        vector,
        embedder,
        entity_id,
        backdate=lambda mid, days: _backdate_neo4j(neo4j_driver, mid, days),
    )
    orchestrator = make_orchestrator(store, vector, embedder)
    result = await run_community_forgetting(store, orchestrator, corpus)

    result.elimination.assert_threshold()
    result.survival.assert_threshold()
    result.retrieval.assert_threshold()
