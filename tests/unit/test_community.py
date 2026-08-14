"""Unit tests for the B5 community detector (deterministic label propagation, #37).

The seam under test is ``CommunityDetector.detect(entity_id) -> {memory_id:
community_id}`` on the in-memory GraphStore. Per the ticket's acceptance
criteria, tests assert only the *partition relationships* — which memories
share a community, which are separated, who is absent — never internal
community ids, member orderings, or numbering.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from emerald.core.community import CommunityDetector
from emerald.core.graph import GraphStore
from emerald.core.mentions import Mention


@pytest.fixture
def graph() -> GraphStore:
    return GraphStore(use_db=False)


@pytest.fixture
def detector(graph: GraphStore) -> CommunityDetector:
    return CommunityDetector(graph=graph)


async def _mem(graph: GraphStore, entity_id: str, content: str = "m") -> str:
    return await graph.create_memory(content, entity_id=entity_id)


async def _edge(graph: GraphStore, from_id: str, to_id: str, rel_type: str = "EXTENDS") -> None:
    await graph.create_relationship(from_id, to_id, rel_type)


async def _clique(graph: GraphStore, entity_id: str, label: str, size: int) -> list[str]:
    """Build a fully connected cluster of relationship edges."""
    ids = [await _mem(graph, entity_id, f"{label}{i}") for i in range(size)]
    for i, first in enumerate(ids):
        for second in ids[i + 1 :]:
            await _edge(graph, first, second)
    return ids


async def _mention(graph: GraphStore, memory_id: str, entity_id: str, canonical: str) -> None:
    await graph.attach_mentions(
        memory_id, entity_id, [Mention(canonical, canonical, "concept", 0.9)]
    )


def _groups(partition: dict[str, str]) -> dict[str, set[str]]:
    """Invert memory_id → community_id into community_id → member set."""
    groups: dict[str, set[str]] = {}
    for memory_id, community_id in partition.items():
        groups.setdefault(community_id, set()).add(memory_id)
    return groups


# ---- empty / degenerate inputs ----


@pytest.mark.asyncio
async def test_empty_entity_returns_empty_partition(detector):
    assert await detector.detect("ghost") == {}


@pytest.mark.asyncio
async def test_isolated_memory_is_its_own_community(detector, graph):
    mid = await _mem(graph, "e1", "lonely fact")
    partition = await detector.detect("e1")
    assert set(partition) == {mid}
    assert len(_groups(partition)) == 1


# ---- synthetic shapes: exact partitions ----


@pytest.mark.asyncio
async def test_chain_is_one_community(detector, graph):
    """a1-EXTENDS->a2-...->a4: a connected chain is a single community."""
    ids = [await _mem(graph, "e1", f"chain{i}") for i in range(4)]
    for first, second in zip(ids, ids[1:], strict=False):
        await _edge(graph, first, second)

    partition = await detector.detect("e1")
    assert set(partition) == set(ids)
    assert len(_groups(partition)) == 1


@pytest.mark.asyncio
async def test_star_is_one_community(detector, graph):
    """A center with DERIVES_FROM leaves is a single community."""
    center = await _mem(graph, "e1", "center")
    leaves = [await _mem(graph, "e1", f"leaf{i}") for i in range(4)]
    for leaf in leaves:
        await _edge(graph, center, leaf, "DERIVES_FROM")

    partition = await detector.detect("e1")
    assert set(partition) == {center, *leaves}
    assert len(_groups(partition)) == 1


@pytest.mark.asyncio
async def test_cycle_is_one_community(detector, graph):
    """A closed UPDATES cycle collapses into a single community."""
    ids = [await _mem(graph, "e1", f"cyc{i}") for i in range(4)]
    for first, second in zip(ids, ids[1:] + ids[:1], strict=False):
        await _edge(graph, first, second, "UPDATES")

    partition = await detector.detect("e1")
    assert set(partition) == set(ids)
    assert len(_groups(partition)) == 1


@pytest.mark.asyncio
async def test_two_cliques_joined_by_one_bridge_split(detector, graph):
    """Two dense clusters joined by a single bridge stay two communities."""
    a = await _clique(graph, "e1", "a", 5)
    b = await _clique(graph, "e1", "b", 5)
    bridge = await _mem(graph, "e1", "bridge")
    await _edge(graph, bridge, a[0])
    await _edge(graph, bridge, b[0])

    partition = await detector.detect("e1")
    groups = _groups(partition)
    assert len(groups) == 2

    a_side = {partition[mid] for mid in a}
    b_side = {partition[mid] for mid in b}
    assert len(a_side) == 1, "cluster A must stay intact"
    assert len(b_side) == 1, "cluster B must stay intact"
    assert a_side != b_side, "the two clusters must be separate communities"
    # The bridge joins exactly one of the two sides, never a third.
    assert partition[bridge] in a_side | b_side


@pytest.mark.asyncio
async def test_two_communities_join_only_through_shared_mentions(detector, graph):
    """Two mention clusters with no relationship edges stay separate."""
    left = [await _mem(graph, "e1", f"left{i}") for i in range(3)]
    right = [await _mem(graph, "e1", f"right{i}") for i in range(3)]
    for mid in left:
        await _mention(graph, mid, "e1", "Python")
    for mid in right:
        await _mention(graph, mid, "e1", "Rust")

    partition = await detector.detect("e1")
    assert len(_groups(partition)) == 2
    assert len({partition[mid] for mid in left}) == 1
    assert len({partition[mid] for mid in right}) == 1
    assert partition[left[0]] != partition[right[0]]


# ---- mention bridges ----


@pytest.mark.asyncio
async def test_shared_mention_bridges_memories(detector, graph):
    """Memories sharing one Mention node form one community even without
    relationship edges."""
    m1 = await _mem(graph, "e1", "uses Python for pipelines")
    m2 = await _mem(graph, "e1", "rewrote the Python service")
    m3 = await _mem(graph, "e1", "unrelated note")
    await _mention(graph, m1, "e1", "Python")
    await _mention(graph, m2, "e1", "Python")

    partition = await detector.detect("e1")
    assert partition[m1] == partition[m2]
    assert partition[m3] != partition[m1]


@pytest.mark.asyncio
async def test_mention_bridge_glues_relationship_clusters(detector, graph):
    """A mention edge between two relationship clusters merges them.

    The fixture is a path (a1-a0-b0-b1): chains converge to a single
    community for every node ordering, so the assertion is deterministic.
    """
    a = await _clique(graph, "e1", "a", 2)
    b = await _clique(graph, "e1", "b", 2)
    await _mention(graph, a[0], "e1", "Shared")
    await _mention(graph, b[0], "e1", "Shared")

    partition = await detector.detect("e1")
    assert len(_groups(partition)) == 1


@pytest.mark.asyncio
async def test_relationship_and_mention_edges_combine(detector, graph):
    """One community spanning both edge kinds: rel + mention chains mix."""
    m1 = await _mem(graph, "e1", "one")
    m2 = await _mem(graph, "e1", "two")
    m3 = await _mem(graph, "e1", "three")
    await _edge(graph, m1, m2)
    await _mention(graph, m2, "e1", "Python")
    await _mention(graph, m3, "e1", "Python")

    partition = await detector.detect("e1")
    assert len({partition[mid] for mid in (m1, m2, m3)}) == 1


# ---- determinism ----


@pytest.mark.asyncio
async def test_repeated_runs_produce_identical_partitions(detector, graph):
    """Same graph, same input → byte-identical partition, every run and
    instance (spec #36 story 8)."""
    a = await _clique(graph, "e1", "a", 4)
    b = await _clique(graph, "e1", "b", 4)
    bridge = await _mem(graph, "e1", "bridge")
    await _edge(graph, bridge, a[0])
    await _edge(graph, bridge, b[0])
    await _mention(graph, a[1], "e1", "Python")
    await _mention(graph, b[1], "e1", "Python")

    first = await detector.detect("e1")
    second = await detector.detect("e1")
    fresh_instance = await CommunityDetector(graph=graph).detect("e1")
    assert first == second == fresh_instance


# ---- isolation and scope ----


@pytest.mark.asyncio
async def test_entity_isolation_excludes_foreign_memories(detector, graph):
    """detect(e1) never returns e2 memories, even when an edge crosses
    the entity boundary (ADR-0002)."""
    m1 = await _mem(graph, "e1", "mine one")
    m2 = await _mem(graph, "e1", "mine two")
    await _edge(graph, m1, m2)
    foreign = await _mem(graph, "e2", "someone else's")
    await _edge(graph, foreign, m1)  # cross-entity edge

    partition = await detector.detect("e1")
    assert set(partition) == {m1, m2}
    assert len(_groups(partition)) == 1

    other = await detector.detect("e2")
    assert set(other) == {foreign}


@pytest.mark.asyncio
async def test_cross_entity_mentions_never_bridge(detector, graph):
    """Same canonical form in two entities stays two nodes, never bridging."""
    mine = await _mem(graph, "e1", "about Google")
    theirs = await _mem(graph, "e2", "about Google")
    await _mention(graph, mine, "e1", "Google")
    await _mention(graph, theirs, "e2", "Google")

    partition = await detector.detect("e1")
    assert set(partition) == {mine}
    assert len(_groups(partition)) == 1


@pytest.mark.asyncio
async def test_historical_memories_do_not_participate(detector, graph):
    """is_latest=false memories are neither members nor glue: two memories
    connected only through history stay separate communities."""
    m1 = await _mem(graph, "e1", "current one")
    m2 = await _mem(graph, "e1", "current two")
    old = await _mem(graph, "e1", "superseded")
    await _edge(graph, old, m1)
    await _edge(graph, old, m2)
    await graph.update_is_latest(old, False)

    partition = await detector.detect("e1")
    assert old not in partition
    assert set(partition) == {m1, m2}
    assert partition[m1] != partition[m2], "history must not glue them together"


# ---- scale guards ----


@pytest.mark.asyncio
async def test_memory_cap_bounds_the_node_set(graph):
    """The per-entity cap bounds how many memories participate."""
    ids = [await _mem(graph, "e1", f"x{i}") for i in range(3)]
    detector = CommunityDetector(graph=graph, max_memories=2)
    partition = await detector.detect("e1")
    assert len(partition) == 2
    assert set(partition) <= set(ids)


@pytest.mark.asyncio
async def test_memory_cap_is_deterministic_with_equal_timestamps(graph):
    """Equal created_at ties at the cap boundary still resolve reproducibly."""
    ids = [await _mem(graph, "e1", f"tie{i}") for i in range(3)]
    same = datetime(2024, 1, 1, tzinfo=UTC)
    for mid in ids:
        memory = await graph.get_memory(mid)
        memory["created_at"] = same

    detector = CommunityDetector(graph=graph, max_memories=2)
    first = await detector.detect("e1")
    second = await detector.detect("e1")
    assert first == second
    assert len(first) == 2
    assert set(first) <= set(ids)


@pytest.mark.asyncio
async def test_iteration_cap_still_yields_deterministic_partitions(graph):
    """A truncated propagation is still a valid, repeatable partition."""
    ids = [await _mem(graph, "e1", f"chain{i}") for i in range(5)]
    for first, second in zip(ids, ids[1:], strict=False):
        await _edge(graph, first, second)

    detector = CommunityDetector(graph=graph, max_iterations=1)
    first = await detector.detect("e1")
    second = await detector.detect("e1")
    assert set(first) == set(ids)
    assert first == second


@pytest.mark.asyncio
async def test_zero_iterations_leaves_every_memory_isolated(graph):
    """max_iterations=0 propagates nothing: every memory stays singleton."""
    ids = [await _mem(graph, "e1", f"c{i}") for i in range(4)]
    for first, second in zip(ids, ids[1:] + ids[:1], strict=False):
        await _edge(graph, first, second)

    detector = CommunityDetector(graph=graph, max_iterations=0)
    partition = await detector.detect("e1")
    assert set(partition) == set(ids)
    assert len(_groups(partition)) == len(ids)
