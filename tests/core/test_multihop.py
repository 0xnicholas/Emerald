"""Tests for MultihopEngine — graph traversal beyond vector similarity (B4).

Ticket #31 (B4 T2): shared-subject bridging — two memories that mention
the same canonical thing (resolved to one Mention node) are siblings
reachable in one hop: Memory-MENTIONS->Mention<-MENTIONS-Memory.

The engine walks MENTIONS bridges only in this ticket; relationship
chains (UPDATES / EXTENDS / DERIVES_FROM) land in #32. Deterministic:
in-memory graph + explicit mentions attached at the graph seam.
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
