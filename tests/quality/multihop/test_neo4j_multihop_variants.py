"""Multihop scenarios on real storage (Neo4j) — B4, tickets #30/#31.

The in-memory multihop suites run everywhere. This module re-runs the
entity-centric retrieval and shared-subject bridging scenarios against a
real Neo4j backend, covering the Cypher branches:

- surface-form resolution and historical/entity isolation in
  get_memories_mentioning (#30)
- shared-subject bridging Memory-MENTIONS->Mention<-MENTIONS-Memory,
  depth bounding and cycle safety on the Cypher branch (#31)

Skipped when no test Neo4j is reachable; the CI `quality-temporal` job
runs it with the compose services up. Later B4 tickets (#32-#34) extend
this file with relationship-chain and path scenarios.
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


async def _run_shared_subject_on_neo4j(driver) -> None:
    """Shared-subject bridging holds on the Cypher branch (#31)."""
    from emerald.core.graph import GraphStore
    from emerald.core.mentions import Mention
    from emerald.core.multihop import MultihopEngine

    store = GraphStore(use_db=True)
    entity_a = "user_quality_multihop_bridge_a"
    entity_b = "user_quality_multihop_bridge_b"
    await _clean_entity(driver, entity_a)
    await _clean_entity(driver, entity_b)

    mid_google = await store.create_memory("在 Google 工作", entity_id=entity_a)
    mid_guge = await store.create_memory("在谷歌工作", entity_id=entity_a)
    mid_both = await store.create_memory("用 Python 写，同时在 Google 工作", entity_id=entity_a)
    mid_python = await store.create_memory("用 Python 写数据管线", entity_id=entity_a)
    await store.attach_mentions(
        mid_google,
        entity_a,
        [Mention("Google", "Google", "organization", 0.9)],
    )
    await store.attach_mentions(
        mid_guge,
        entity_a,
        [Mention("谷歌", "Google", "organization", 0.9)],
    )
    await store.attach_mentions(
        mid_both,
        entity_a,
        [
            Mention("Python", "Python", "technology", 0.9),
            Mention("Google", "Google", "organization", 0.9),
        ],
    )
    await store.attach_mentions(
        mid_python,
        entity_a,
        [Mention("Python", "Python", "technology", 0.9)],
    )
    # Entity B mirrors the Google memory — must never bridge into A.
    mid_b = await store.create_memory("在 Google 工作", entity_id=entity_b)
    await store.attach_mentions(
        mid_b,
        entity_b,
        [Mention("Google", "Google", "organization", 0.9)],
    )

    engine = MultihopEngine(graph=store)
    hops = await engine.expand([mid_google], entity_a, depth=2)
    assert set(hops) == {mid_guge, mid_both, mid_python}
    assert hops[mid_guge].depth == 1
    assert hops[mid_both].depth == 1
    # The Python memory is two hops away via the shared Google∩Python memory.
    assert hops[mid_python].depth == 2
    assert mid_b not in hops

    # depth=0 is the status quo: no bridging.
    assert await engine.expand([mid_google], entity_a, depth=0) == {}

    # Cycle safety: expanding from both ends yields each memory once.
    hops = await engine.expand([mid_google, mid_guge], entity_a, depth=3)
    assert mid_both in hops and mid_python in hops
    ids = list(hops)
    assert len(ids) == len(set(ids))


@pytest.mark.asyncio
async def test_entity_centric_on_neo4j(neo4j_driver):
    """Entity-centric retrieval holds on a real Neo4j backend."""
    await _run_entity_centric_on_neo4j(neo4j_driver)
    await _run_shared_subject_on_neo4j(neo4j_driver)
