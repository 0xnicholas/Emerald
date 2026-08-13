"""Multihop scenarios on real storage (Neo4j) — B4, ticket #30.

The in-memory multihop suites run everywhere. This module re-runs the
entity-centric retrieval scenario against a real Neo4j backend, covering
the Cypher branch of get_memories_mentioning:

- surface-form resolution on the Cypher branch (Google / 谷歌 → one node)
- historical memories excluded (is_latest=false)
- cross-entity isolation — entity A's about never surfaces entity B
- mention-id lookup returns exactly that node's memories

Skipped when no test Neo4j is reachable; the CI `quality-temporal` job
runs it with the compose services up. Later B4 tickets (#31-#34) extend
this file with bridging / chain / path scenarios.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.quality]


async def _clean_entity(driver, entity: str) -> None:
    """Remove an entity's memories, mentions and entity node (clean slate)."""
    async with driver.session() as session:
        await session.run(
            "MATCH (m:Memory) WHERE m.entity_id = $e DETACH DELETE m", e=entity,
        )
        await session.run(
            "MATCH (mn:Mention) WHERE mn.entity_id = $e DETACH DELETE mn", e=entity,
        )
        await session.run(
            "MATCH (e:Entity) WHERE e.id = $e DETACH DELETE e", e=entity,
        )


async def _run_entity_centric_on_neo4j(driver) -> None:
    """about retrieval resolves surface forms + isolates on the Cypher branch."""
    from emerald.core.graph import GraphStore
    from emerald.core.mentions import Mention

    store = GraphStore(use_db=True)
    entity_a = "user_quality_multihop_about_a"
    entity_b = "user_quality_multihop_about_b"
    await _clean_entity(driver, entity_a)
    await _clean_entity(driver, entity_b)

    mids_a = []
    for surface in ("Google", "谷歌", "GOOGLE"):
        mid = await store.create_memory(f"在 {surface} 工作", entity_id=entity_a)
        await store.attach_mentions(
            mid, entity_a, [Mention(surface, "Google", "organization", 0.9)],
        )
        mids_a.append(mid)
    mid_stripe = await store.create_memory("在 Stripe 工作", entity_id=entity_a)
    await store.attach_mentions(
        mid_stripe, entity_a, [Mention("Stripe", "Stripe", "organization", 0.9)],
    )
    # Historical memory: replaced → excluded from plain about retrieval.
    mid_old = await store.create_memory("过去在 Google 工作", entity_id=entity_a)
    await store.attach_mentions(
        mid_old, entity_a, [Mention("Google", "Google", "organization", 0.9)],
    )
    await store.update_is_latest(mid_old, False, replaced_by=mids_a[0])

    # Entity B mentions Google too — must never surface for A.
    mid_b = await store.create_memory("在 Google 工作", entity_id=entity_b)
    await store.attach_mentions(
        mid_b, entity_b, [Mention("Google", "Google", "organization", 0.9)],
    )

    # Canonical-form lookup: all surface forms, no historical, no cross-entity.
    memories = await store.get_memories_mentioning(entity_a, "Google")
    assert {m["id"] for m in memories} == set(mids_a)
    assert mid_stripe not in {m["id"] for m in memories}
    assert mid_old not in {m["id"] for m in memories}
    assert mid_b not in {m["id"] for m in memories}

    # Unknown canonical → empty, not an error.
    assert await store.get_memories_mentioning(entity_a, "NoSuchThing") == []

    # Mention-id lookup: exactly that node's memory.
    nodes = await store.get_entity_mentions(entity_a)
    google_node = next(n for n in nodes if n["canonical_form"] == "Google")
    by_id = await store.get_memories_mentioning(entity_a, google_node["id"])
    assert {m["id"] for m in by_id} == set(mids_a)


@pytest.mark.asyncio
async def test_entity_centric_on_neo4j(neo4j_driver):
    """Entity-centric retrieval holds on a real Neo4j backend."""
    await _run_entity_centric_on_neo4j(neo4j_driver)
