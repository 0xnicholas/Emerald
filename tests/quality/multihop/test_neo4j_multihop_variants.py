"""Multihop scenarios on real storage (Neo4j) — B4, tickets #30-#32.

The in-memory multihop suites run everywhere. This module re-runs the
entity-centric retrieval, shared-subject bridging and relationship-chain
scenarios against a real Neo4j backend, covering the Cypher branches:

- surface-form resolution and historical/entity isolation in
  get_memories_mentioning (#30)
- shared-subject bridging Memory-MENTIONS->Mention<-MENTIONS-Memory,
  depth bounding and cycle safety on the Cypher branch (#31)
- relationship chains over UPDATES / EXTENDS / DERIVES_FROM via
  get_relationship_neighbors: reverse DERIVES_FROM, chained depth ≥ 2,
  UPDATES-surfaced history marked and terminal (#32)

Skipped when no test Neo4j is reachable; the CI `quality-temporal` job
runs it with the compose services up. Later B4 tickets (#33-#34) extend
this file with unified-path and ranking scenarios.
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


async def _run_relationship_chains_on_neo4j(driver) -> None:
    """Relationship chains hold on the Cypher branch (#32)."""
    from emerald.core.graph import GraphStore
    from emerald.core.mentions import Mention
    from emerald.core.multihop import MultihopEngine

    store = GraphStore(use_db=True)
    entity_a = "user_quality_multihop_rel_a"
    entity_b = "user_quality_multihop_rel_b"
    await _clean_entity(driver, entity_a)
    await _clean_entity(driver, entity_b)

    async def seed(entity, content):
        return await store.create_memory(content, entity_id=entity)

    mid_a = await seed(entity_a, "猫在房顶上睡觉")
    mid_a2 = await seed(entity_a, "冰箱里有牛奶")
    mid_d1 = await seed(entity_a, "窗外下着大雨")
    mid_d2 = await seed(entity_a, "桌上放着铅笔")
    mid_x = await seed(entity_a, "河里游着金鱼")
    await store.attach_mentions(
        mid_a2, entity_a, [Mention("Foo", "Foo", "concept", 0.9)],
    )
    # A2 supersedes A → A historical; D chain off A2; X extends A2.
    await store.create_update_relation(mid_a2, mid_a)
    await store.create_relationship(mid_d1, mid_a2, "DERIVES_FROM")
    await store.create_relationship(mid_d2, mid_d1, "DERIVES_FROM")
    await store.create_relationship(mid_x, mid_a2, "EXTENDS")
    # Cross-entity edge: another entity's fact derives from D1 — the
    # Cypher branch must filter it out of the walk.
    mid_b = await seed(entity_b, "天上飘着白云")
    await store.create_relationship(mid_b, mid_d1, "DERIVES_FROM")

    engine = MultihopEngine(graph=store)

    # Reverse DERIVES_FROM + UPDATES history at depth 1.
    hops = await engine.expand([mid_a2], entity_a, depth=1)
    assert set(hops) == {mid_a, mid_d1, mid_x}
    assert hops[mid_a].historical is True
    assert hops[mid_a].path == [("memory", mid_a2), ("UPDATES", mid_a)]
    assert hops[mid_d1].historical is False

    # Chained derivation at depth 2, exactly.
    hops = await engine.expand([mid_a2], entity_a, depth=2)
    assert set(hops) == {mid_a, mid_d1, mid_d2, mid_x}
    assert hops[mid_d2].depth == 2
    assert hops[mid_d2].path == [
        ("memory", mid_a2),
        ("DERIVES_FROM", mid_d1),
        ("DERIVES_FROM", mid_d2),
    ]

    # Historical nodes are terminals and cross-entity edges never surface.
    mid_ext = await seed(entity_a, "北京冬天很冷")
    await store.create_relationship(mid_ext, mid_a, "EXTENDS")
    hops = await engine.expand([mid_a2], entity_a, depth=3)
    assert mid_ext not in hops
    assert mid_b not in hops

    # Depth cap: the walk never exceeds MAX_DEPTH=4.
    chain = [await seed(entity_a, f"链上事实 {i}") for i in range(6)]
    for derived, source in zip(chain[1:], chain, strict=False):
        await store.create_relationship(derived, source, "DERIVES_FROM")
    hops = await engine.expand([chain[0]], entity_a, depth=99)
    assert chain[4] in hops and chain[5] not in hops
    assert hops[chain[4]].depth == 4


@pytest.mark.asyncio
async def test_entity_centric_on_neo4j(neo4j_driver):
    """Entity-centric retrieval holds on a real Neo4j backend."""
    await _run_entity_centric_on_neo4j(neo4j_driver)
    await _run_shared_subject_on_neo4j(neo4j_driver)
    await _run_relationship_chains_on_neo4j(neo4j_driver)
