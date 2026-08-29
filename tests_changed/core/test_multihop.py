"""Tests for MultihopEngine — graph traversal beyond vector similarity (B4).

Ticket #31 (B4 T2): shared-subject bridging — two memories that mention
the same canonical thing (resolved to one Mention node) are siblings
reachable in one hop: Memory-MENTIONS->Mention<-MENTIONS-Memory.

Ticket #32 (B4 T3): relationship chains — one hop may also walk
UPDATES / EXTENDS / DERIVES_FROM bidirectionally, and derived facts
participate as sources in the next hop (D2 -DF-> D1 -DF-> A surfaces
d2 at depth 2 from A). Historical nodes (is_latest=False) surface only
when stepped on along an UPDATES edge, are marked ``historical``, and
are terminals (never expanded further). Deterministic: in-memory graph
+ explicit mentions/relationships attached at the graph seam.
"""

import pytest

from emerald.core.graph import GraphStore
from emerald.core.mentions import Mention
from emerald.core.multihop import MultihopEngine


@pytest.fixture
def graph():
    return GraphStore(use_db=False)


@pytest.fixture
def engine(graph):
    return MultihopEngine(graph=graph)


async def _seed(graph, entity, content, mentions):
    mid = await graph.create_memory(content, entity_id=entity)
    await graph.attach_mentions(mid, entity, mentions)
    return mid


@pytest.mark.asyncio
async def test_bridge_shared_mention_depth1(graph, engine):
    """Different surface forms of one canonical resolve to one bridge hop."""
    mid_a = await _seed(graph, "e1", "在 Google 工作", [
        Mention("Google", "Google", "organization", 0.9),
    ])
    mid_b = await _seed(graph, "e1", "在谷歌工作", [
        Mention("谷歌", "Google", "organization", 0.9),
    ])
    mid_c = await _seed(graph, "e1", "在 Stripe 工作", [
        Mention("Stripe", "Stripe", "organization", 0.9),
    ])

    hops = await engine.expand([mid_a], "e1", depth=1)
    assert set(hops) == {mid_b}
    assert mid_c not in hops
    assert hops[mid_b].depth == 1


@pytest.mark.asyncio
async def test_depth0_returns_no_hops(graph, engine):
    """depth=0 is the status quo: no graph traversal."""
    mid_a = await _seed(graph, "e1", "在 Google 工作", [
        Mention("Google", "Google", "organization", 0.9),
    ])
    await _seed(graph, "e1", "在谷歌工作", [
        Mention("谷歌", "Google", "organization", 0.9),
    ])

    assert await engine.expand([mid_a], "e1", depth=0) == {}


@pytest.mark.asyncio
async def test_depth2_chains_through_a_shared_subject(graph, engine):
    """A↔X↔B↔Y↔C: C is two hops from A, with a full path."""
    mid_a = await _seed(graph, "e1", "事实 A", [
        Mention("X", "X", "concept", 0.9),
    ])
    mid_b = await _seed(graph, "e1", "事实 B", [
        Mention("X", "X", "concept", 0.9),
        Mention("Y", "Y", "concept", 0.9),
    ])
    mid_c = await _seed(graph, "e1", "事实 C", [
        Mention("Y", "Y", "concept", 0.9),
    ])

    hops = await engine.expand([mid_a], "e1", depth=2)
    assert set(hops) == {mid_b, mid_c}
    assert hops[mid_b].depth == 1
    assert hops[mid_c].depth == 2
    # The path is seed → mention → memory → mention → memory.
    assert hops[mid_c].path == [
        ("memory", mid_a),
        ("mention", hops[mid_b].path[1][1]),
        ("memory", mid_b),
        ("mention", hops[mid_c].path[3][1]),
        ("memory", mid_c),
    ]


@pytest.mark.asyncio
async def test_type_participates_in_the_bridge(graph, engine):
    """Same canonical form, different types → different nodes, no bridge."""
    mid_org = await _seed(graph, "e1", "在 Apple 工作", [
        Mention("Apple", "Apple", "organization", 0.9),
    ])
    mid_tech = await _seed(graph, "e1", "用 Apple 设备", [
        Mention("Apple", "Apple", "technology", 0.9),
    ])

    assert await engine.expand([mid_org], "e1", depth=1) == {}
    assert await engine.expand([mid_tech], "e1", depth=1) == {}


@pytest.mark.asyncio
async def test_cycle_safe_no_duplicates(graph, engine):
    """Mutually-referencing memories bridge once, never twice."""
    mid_a = await _seed(graph, "e1", "在 Google 工作", [
        Mention("Google", "Google", "organization", 0.9),
    ])
    mid_b = await _seed(graph, "e1", "在谷歌工作", [
        Mention("谷歌", "Google", "organization", 0.9),
    ])

    hops = await engine.expand([mid_a], "e1", depth=3)
    # B is reachable from A; the A↔B cycle never re-adds A (seed/visited).
    assert set(hops) == {mid_b}
    assert hops[mid_b].depth == 1


@pytest.mark.asyncio
async def test_bridge_entity_scoped(graph, engine):
    """Bridging never crosses the entity's context pool."""
    mid_a = await _seed(graph, "e1", "在 Google 工作", [
        Mention("Google", "Google", "organization", 0.9),
    ])
    mid_b = await _seed(graph, "e2", "在 Google 工作", [
        Mention("Google", "Google", "organization", 0.9),
    ])

    hops = await engine.expand([mid_a], "e1", depth=2)
    assert mid_b not in hops


@pytest.mark.asyncio
async def test_seeds_are_not_returned_as_hops(graph, engine):
    """The seed set itself is never part of the hop results."""
    mid_a = await _seed(graph, "e1", "在 Google 工作", [
        Mention("Google", "Google", "organization", 0.9),
    ])
    await _seed(graph, "e1", "在谷歌工作", [
        Mention("谷歌", "Google", "organization", 0.9),
    ])

    hops = await engine.expand([mid_a], "e1", depth=1)
    assert mid_a not in hops


@pytest.mark.asyncio
async def test_bridge_excludes_historical_memories(graph, engine):
    """Replaced (is_latest=False) memories are not bridged to."""
    mid_a = await _seed(graph, "e1", "在 Google 工作", [
        Mention("Google", "Google", "organization", 0.9),
    ])
    mid_b = await _seed(graph, "e1", "过去在谷歌工作", [
        Mention("谷歌", "Google", "organization", 0.9),
    ])
    await graph.update_is_latest(mid_b, False, replaced_by=mid_a)

    hops = await engine.expand([mid_a], "e1", depth=2)
    assert mid_b not in hops


# ---- Relationship chains (B4, ticket #32) ----


async def _seed_plain(graph, entity, content):
    """Seed a memory with no mentions (relationship-only scenarios)."""
    return await graph.create_memory(content, entity_id=entity)


@pytest.mark.asyncio
async def test_reverse_derives_from_surfaces_derived(graph, engine):
    """Querying a source fact surfaces the fact derived from it (1 hop)."""
    mid_a = await _seed_plain(graph, "e1", "用户住在北京")
    mid_d = await _seed_plain(graph, "e1", "用户在中国")
    await graph.create_relationship(mid_d, mid_a, "DERIVES_FROM")

    hops = await engine.expand([mid_a], "e1", depth=1)
    assert set(hops) == {mid_d}
    assert hops[mid_d].depth == 1
    assert hops[mid_d].historical is False
    assert hops[mid_d].path == [("memory", mid_a), ("DERIVES_FROM", mid_d)]


@pytest.mark.asyncio
async def test_derives_chain_depth2_exact(graph, engine):
    """D2 -DF-> D1 -DF-> A: from A, D1 at depth 1 and D2 at depth 2."""
    mid_a = await _seed_plain(graph, "e1", "用户住在北京")
    mid_d1 = await _seed_plain(graph, "e1", "用户在中国")
    mid_d2 = await _seed_plain(graph, "e1", "用户在亚洲")
    await graph.create_relationship(mid_d1, mid_a, "DERIVES_FROM")
    await graph.create_relationship(mid_d2, mid_d1, "DERIVES_FROM")

    depth1 = await engine.expand([mid_a], "e1", depth=1)
    assert set(depth1) == {mid_d1}
    assert depth1[mid_d1].depth == 1

    depth2 = await engine.expand([mid_a], "e1", depth=2)
    assert set(depth2) == {mid_d1, mid_d2}
    assert depth2[mid_d1].depth == 1
    assert depth2[mid_d2].depth == 2
    # Chain provenance: the second edge hangs off the first derived fact.
    assert depth2[mid_d2].path == [
        ("memory", mid_a),
        ("DERIVES_FROM", mid_d1),
        ("DERIVES_FROM", mid_d2),
    ]


@pytest.mark.asyncio
async def test_extends_walks_both_directions(graph, engine):
    """EXTENDS enriches in both directions; both facts stay latest."""
    mid_a = await _seed_plain(graph, "e1", "用户喜欢 Python")
    mid_b = await _seed_plain(graph, "e1", "用户用 Python 写后端")
    await graph.create_relationship(mid_b, mid_a, "EXTENDS")

    forward = await engine.expand([mid_a], "e1", depth=1)
    assert set(forward) == {mid_b}
    assert forward[mid_b].path == [("memory", mid_a), ("EXTENDS", mid_b)]

    reverse = await engine.expand([mid_b], "e1", depth=1)
    assert set(reverse) == {mid_a}
    assert reverse[mid_a].historical is False


@pytest.mark.asyncio
async def test_updates_chain_surfaces_historical_marked(graph, engine):
    """The superseded node appears via UPDATES and is marked historical."""
    mid_old = await _seed_plain(graph, "e1", "用户住在北京")
    mid_new = await _seed_plain(graph, "e1", "用户搬到了上海")
    await graph.create_update_relation(mid_new, mid_old)

    hops = await engine.expand([mid_new], "e1", depth=1)
    assert set(hops) == {mid_old}
    assert hops[mid_old].depth == 1
    assert hops[mid_old].historical is True
    assert hops[mid_old].path == [("memory", mid_new), ("UPDATES", mid_old)]


@pytest.mark.asyncio
async def test_historical_node_is_terminal(graph, engine):
    """A historical node is returned but never expanded further."""
    mid_old = await _seed_plain(graph, "e1", "用户住在北京")
    mid_new = await _seed_plain(graph, "e1", "用户搬到了上海")
    mid_ext = await _seed_plain(graph, "e1", "北京冬天很冷")
    await graph.create_relationship(mid_ext, mid_old, "EXTENDS")
    await graph.create_update_relation(mid_new, mid_old)

    hops = await engine.expand([mid_new], "e1", depth=2)
    # The EXTENDS neighbor of the historical node is out of reach: history
    # is surfaced, not walked through.
    assert set(hops) == {mid_old}
    assert mid_ext not in hops


@pytest.mark.asyncio
async def test_history_only_surfaces_along_updates(graph, engine):
    """EXTENDS/DERIVES_FROM never reach into historical nodes."""
    mid_a = await _seed_plain(graph, "e1", "用户喜欢 Python")
    mid_b = await _seed_plain(graph, "e1", "用户用 Python 写后端")
    mid_b2 = await _seed_plain(graph, "e1", "用户用 Go 写后端")
    await graph.create_relationship(mid_b, mid_a, "EXTENDS")
    await graph.create_update_relation(mid_b2, mid_b)

    hops = await engine.expand([mid_a], "e1", depth=2)
    assert hops == {}


@pytest.mark.asyncio
async def test_relationship_walk_is_entity_scoped(graph, engine):
    """Relationship hops never cross the entity's context pool."""
    mid_a = await _seed_plain(graph, "e1", "用户住在北京")
    mid_other = await _seed_plain(graph, "e2", "别人住在上海")
    await graph.create_relationship(mid_a, mid_other, "EXTENDS")

    hops = await engine.expand([mid_a], "e1", depth=1)
    assert mid_other not in hops


@pytest.mark.asyncio
async def test_relationship_cycle_safe(graph, engine):
    """Mutually-referencing memories surface once at the shallowest depth."""
    mid_a = await _seed_plain(graph, "e1", "用户喜欢 Python")
    mid_b = await _seed_plain(graph, "e1", "用户用 Python 写后端")
    await graph.create_relationship(mid_a, mid_b, "EXTENDS")
    await graph.create_relationship(mid_b, mid_a, "EXTENDS")

    hops = await engine.expand([mid_a], "e1", depth=3)
    assert set(hops) == {mid_b}
    assert hops[mid_b].depth == 1


@pytest.mark.asyncio
async def test_depth_cap_at_four(graph, engine):
    """A 5-edge DERIVES chain is cut at depth 4 (spec #29 上限 4)."""
    mids = [await _seed_plain(graph, "e1", f"事实 {i}") for i in range(6)]
    for derived, source in zip(mids[1:], mids, strict=False):
        await graph.create_relationship(derived, source, "DERIVES_FROM")

    hops = await engine.expand([mids[0]], "e1", depth=5)
    # Depth is clamped to MAX_DEPTH=4: mids[1..4] reachable, mids[5] not.
    assert set(hops) == set(mids[1:5])
    assert hops[mids[4]].depth == 4


@pytest.mark.asyncio
async def test_mixed_mention_and_relationship_chain(graph, engine):
    """One walk may interleave mention bridges and relationship hops."""
    mid_a = await _seed(graph, "e1", "在 Google 工作", [
        Mention("Google", "Google", "organization", 0.9),
    ])
    mid_b = await _seed(graph, "e1", "在谷歌工作", [
        Mention("谷歌", "Google", "organization", 0.9),
    ])
    mid_d = await _seed_plain(graph, "e1", "用户在大厂工作")
    await graph.create_relationship(mid_d, mid_b, "DERIVES_FROM")

    hops = await engine.expand([mid_a], "e1", depth=2)
    assert set(hops) == {mid_b, mid_d}
    assert hops[mid_b].depth == 1
    assert hops[mid_d].depth == 2
    assert hops[mid_d].path == [
        ("memory", mid_a),
        ("mention", hops[mid_b].path[1][1]),
        ("memory", mid_b),
        ("DERIVES_FROM", mid_d),
    ]
