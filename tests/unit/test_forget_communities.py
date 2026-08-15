"""Engine-level tests for the B5 forget_communities strategy (#39).

The seam under test is ``ForgetEngine.forget_communities(entity_id=None)``
on the in-memory GraphStore: enumerate entities → detect communities →
score → decide → forget low-activity communities through the existing
``mark_expired`` seam (reason ``community_forgotten``), with profile /
bridge exemptions, entity isolation, mention pruning, metrics, and
deterministic outcomes. Exact forgotten-set assertions wherever the
partition is id-independent; bridge fixtures assert the invariant
(bridge + exactly one boundary endpoint survive).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from emerald.core.forget import ForgetEngine
from emerald.core.graph import GraphStore
from emerald.core.mentions import Mention
from emerald.core.metrics import forget_communities_total

OLD = datetime.now(UTC) - timedelta(days=120)


@pytest.fixture
def graph() -> GraphStore:
    return GraphStore(use_db=False)


@pytest.fixture
def engine(graph: GraphStore) -> ForgetEngine:
    # 密闭性：禁用 Redis 画像缓存（redis_client=False → 跳过自动发现）。
    # 否则带 Redis service 的 CI（benchmark.yml）会被先前测试写入的
    # profile:<entity> 键污染——本文件的图是每 fixture 全新的内存图，
    # 而共享缓存返回的是别的测试的图算出的画像（2026-08-15 CI 红根因）。
    from emerald.core.profile import ProfileManager

    return ForgetEngine(
        graph=graph,
        profile_manager=ProfileManager(graph=graph, redis_client=False),
    )


async def _mem(
    graph: GraphStore,
    entity_id: str,
    content: str,
    *,
    confidence: float = 0.8,
    days_old: int = 0,
) -> str:
    mid = await graph.create_memory(content, entity_id=entity_id, confidence=confidence)
    memory = await graph.get_memory(mid)
    memory["created_at"] = datetime.now(UTC) - timedelta(days=days_old)
    return mid


async def _clique(
    graph: GraphStore,
    entity_id: str,
    label: str,
    size: int,
    *,
    confidence: float = 0.8,
    days_old: int = 0,
) -> list[str]:
    ids = [
        await _mem(graph, entity_id, f"{label}{i}", confidence=confidence, days_old=days_old)
        for i in range(size)
    ]
    for i, first in enumerate(ids):
        for second in ids[i + 1 :]:
            await graph.create_relationship(first, second, "EXTENDS")
    return ids


async def _mention(graph: GraphStore, memory_id: str, entity_id: str, canonical: str) -> None:
    await graph.attach_mentions(
        memory_id, entity_id, [Mention(canonical, canonical, "concept", 0.9)]
    )


def _counter(action: str) -> float:
    return forget_communities_total.labels(action=action)._value.get()


# ---- wholesale forgetting of stale communities ----


@pytest.mark.asyncio
async def test_stale_community_forgotten_wholesale(engine, graph):
    """A stale, low-confidence clique is forgotten in one run, with the
    community_forgotten reason, through the existing mark_expired seam."""
    stale = await _clique(graph, "e1", "stale", 3, confidence=0.2, days_old=120)

    count = await engine.forget_communities("e1")
    assert count == 3

    for mid in stale:
        memory = await graph.get_memory(mid)
        assert memory["is_latest"] is False
        assert memory["replaced_by"] == "community_forgotten"
        assert memory["expired_at"] is not None


@pytest.mark.asyncio
async def test_active_community_kept(engine, graph):
    """Recent high-confidence communities survive untouched."""
    active = await _clique(graph, "e1", "active", 3, confidence=0.8, days_old=1)

    count = await engine.forget_communities("e1")
    assert count == 0
    for mid in active:
        assert (await graph.get_memory(mid))["is_latest"] is True


# ---- bridge exemption ----


@pytest.mark.asyncio
async def test_bridge_survives_while_stale_cohort_forgotten(engine, graph):
    """Two stale cliques joined by one bridge: the bridge and exactly one
    boundary endpoint survive (connectivity); the remaining 9 members are
    forgotten."""
    a = await _clique(graph, "e1", "a", 5, confidence=0.2, days_old=120)
    b = await _clique(graph, "e1", "b", 5, confidence=0.2, days_old=120)
    bridge = await _mem(graph, "e1", "bridge", confidence=0.2, days_old=120)
    await graph.create_relationship(bridge, a[0], "EXTENDS")
    await graph.create_relationship(bridge, b[0], "EXTENDS")

    count = await engine.forget_communities("e1")
    assert count == 9

    assert (await graph.get_memory(bridge))["is_latest"] is True
    survivors = [mid for mid in a + b if (await graph.get_memory(mid))["is_latest"]]
    # Exactly one boundary endpoint (one of the bridge's two neighbors) lives.
    assert len(survivors) == 1
    assert survivors[0] in (a[0], b[0])


# ---- profile exemption ----


@pytest.mark.asyncio
async def test_profile_referenced_stale_memory_exempt(engine, graph):
    """A stale singleton that the profile references is exempt even though
    its activity score is below threshold; an unreferenced twin is not."""
    referenced = await _mem(graph, "e1", "user prefers X", confidence=0.8, days_old=120)
    unreferenced = await _mem(graph, "e1", "stale noise", confidence=0.2, days_old=120)

    count = await engine.forget_communities("e1")
    assert count == 1

    assert (await graph.get_memory(referenced))["is_latest"] is True
    assert (await graph.get_memory(unreferenced))["is_latest"] is False


# ---- mention pruning rides the seam ----


@pytest.mark.asyncio
async def test_forgetting_prunes_mentions_and_orphan_nodes(engine, graph):
    """Forgotten memories lose their MENTIONS edges and orphaned Mention
    nodes are pruned; surviving memories keep theirs."""
    stale = await _clique(graph, "e1", "stale", 2, confidence=0.2, days_old=120)
    active = await _mem(graph, "e1", "recent Python work", confidence=0.8, days_old=1)
    for mid in stale:
        await _mention(graph, mid, "e1", "OldProject")
    await _mention(graph, active, "e1", "Python")

    assert await engine.forget_communities("e1") == 2

    for mid in stale:
        assert await graph.get_memory_mentions(mid) == []
    mention_nodes = await graph.get_entity_mentions("e1")
    assert "OldProject" not in {n["canonical_form"] for n in mention_nodes}
    assert "Python" in {n["canonical_form"] for n in mention_nodes}


# ---- isolation and scope ----


@pytest.mark.asyncio
async def test_entity_scoped_run_does_not_touch_others(engine, graph):
    mine = await _clique(graph, "e1", "mine", 2, confidence=0.2, days_old=120)
    theirs = await _clique(graph, "e2", "theirs", 2, confidence=0.2, days_old=120)

    assert await engine.forget_communities("e1") == 2
    for mid in mine:
        assert (await graph.get_memory(mid))["is_latest"] is False
    for mid in theirs:
        assert (await graph.get_memory(mid))["is_latest"] is True

    assert await engine.forget_communities() == 2  # full sweep catches e2
    for mid in theirs:
        assert (await graph.get_memory(mid))["is_latest"] is False


@pytest.mark.asyncio
async def test_empty_graph_returns_zero(engine):
    assert await engine.forget_communities("ghost") == 0
    assert await engine.forget_communities() == 0


# ---- observability: metrics per action ----


@pytest.mark.asyncio
async def test_metrics_count_decisions_by_action(engine, graph):
    await _clique(graph, "e1", "stale", 2, confidence=0.2, days_old=120)
    await _clique(graph, "e1", "active", 2, confidence=0.8, days_old=1)
    await _mem(graph, "e1", "pref", confidence=0.8, days_old=120)

    before = {a: _counter(a) for a in ("forgotten", "keep", "exempt_bridge", "exempt_profile")}
    await engine.forget_communities("e1")

    # stale community → forgotten; active community → keep; referenced singleton → exempt_profile.
    assert _counter("forgotten") == before["forgotten"] + 1
    assert _counter("keep") == before["keep"] + 1
    assert _counter("exempt_profile") == before["exempt_profile"] + 1
    assert _counter("exempt_bridge") == before["exempt_bridge"]


# ---- determinism ----


@pytest.mark.asyncio
async def test_second_run_finds_nothing_left(engine, graph):
    """Forgetting is idempotent: after the first run the graph is stable
    and a second run forgets nothing more."""
    await _clique(graph, "e1", "stale", 2, confidence=0.2, days_old=120)
    await _clique(graph, "e1", "active", 2, confidence=0.8, days_old=1)

    assert await engine.forget_communities("e1") == 2
    assert await engine.forget_communities("e1") == 0


@pytest.mark.asyncio
async def test_identical_entities_decide_identically(engine, graph):
    """Structurally identical entities yield identical outcomes."""
    for eid in ("e1", "e2"):
        await _clique(graph, eid, "stale", 2, confidence=0.2, days_old=120)
        await _clique(graph, eid, "active", 2, confidence=0.8, days_old=1)

    first = await engine.forget_communities("e1")
    second = await engine.forget_communities("e2")
    assert first == second == 2
