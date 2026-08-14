"""Engine-level tests for the B6 consolidate_duplicates strategy (#44).

The seam under test is ``ForgetEngine.consolidate_duplicates(entity_id=None)``
on the in-memory GraphStore + VectorStore with the deterministic mock
embedder: enumerate entities → vector candidates (T1) → guardrail
verdicts → land merges through the ``mark_consolidated`` seam (T2),
with group-level convergence to a single representative, vetoed pairs
kept as-is, entity isolation, per-decision metrics, per-entity failure
isolation, and deterministic/idempotent outcomes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from emerald.core.duplicates import DuplicateConfig, DuplicatesDetector
from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.forget import ForgetEngine
from emerald.core.graph import GraphStore
from emerald.core.metrics import consolidate_duplicates_total
from emerald.core.vector import VectorStore

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


@pytest.fixture
def graph() -> GraphStore:
    return GraphStore(use_db=False)


@pytest.fixture
def vector() -> VectorStore:
    return VectorStore(use_db=False)


@pytest.fixture
def embedder() -> MockEmbeddingProvider:
    return MockEmbeddingProvider(dimension=32)


async def _seed(
    graph: GraphStore,
    vector: VectorStore,
    embedder: MockEmbeddingProvider,
    content: str,
    *,
    entity_id: str = "e1",
    memory_type: str = "fact",
    confidence: float = 0.4,
    days_old: int = 0,
) -> str:
    """Create a memory, backdate it, and index it into the vector store —
    the same record a pipeline ingest would produce (mirrors the T1
    detector fixtures)."""
    mid = await graph.create_memory(
        content, entity_id=entity_id, memory_type=memory_type, confidence=confidence
    )
    memory = await graph.get_memory(mid)
    memory["created_at"] = NOW - timedelta(days=days_old)
    embedding = (await embedder.embed([content]))[0]
    await vector.store(mid, content, embedding, entity_id=entity_id)
    return mid


def make_engine(
    graph: GraphStore,
    vector: VectorStore,
    config: DuplicateConfig | None = None,
) -> ForgetEngine:
    return ForgetEngine(graph=graph, vector_store=vector, duplicate_config=config)


def _counter(action: str) -> float:
    return consolidate_duplicates_total.labels(action=action)._value.get()


# ---- convergence to a single representative ----


@pytest.mark.asyncio
async def test_duplicate_pair_converges_on_representative(graph, vector, embedder):
    """A near-duplicate pair collapses into the newer memory; the merged
    memory becomes historical with replaced_by pointing at the
    representative and metadata reason=consolidated."""
    older = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=30)
    newer = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=0)

    count = await make_engine(graph, vector).consolidate_duplicates("e1")
    assert count == 1

    rep = await graph.get_memory(newer)
    assert rep["is_latest"] is True
    assert rep.get("replaced_by") is None

    merged = await graph.get_memory(older)
    assert merged["is_latest"] is False
    assert merged["replaced_by"] == newer
    assert merged["expired_at"] is not None
    assert merged["metadata"].get("reason") == "consolidated"


@pytest.mark.asyncio
async def test_triple_group_converges_on_single_representative(graph, vector, embedder):
    """Three pairwise duplicates collapse to exactly one latest memory;
    both merged memories point at the same representative."""
    first = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=30)
    second = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=15)
    newest = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=0)

    count = await make_engine(graph, vector).consolidate_duplicates("e1")
    assert count == 2

    survivors = [
        mid for mid in (first, second, newest) if (await graph.get_memory(mid))["is_latest"]
    ]
    assert survivors == [newest]
    for mid in (first, second):
        assert (await graph.get_memory(mid))["replaced_by"] == newest


@pytest.mark.asyncio
async def test_two_independent_groups_converge_separately(graph, vector, embedder):
    """Two unrelated duplicate groups in one entity each converge on their
    own representative — one group's merge never leaks into the other."""
    a1 = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=30)
    a2 = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=0)
    b1 = await _seed(graph, vector, embedder, "用户喜欢喝咖啡", confidence=0.4, days_old=20)
    b2 = await _seed(graph, vector, embedder, "用户喜欢喝咖啡", confidence=0.4, days_old=1)

    count = await make_engine(graph, vector).consolidate_duplicates("e1")
    assert count == 2

    assert (await graph.get_memory(a2))["is_latest"] is True
    assert (await graph.get_memory(b2))["is_latest"] is True
    assert (await graph.get_memory(a1))["replaced_by"] == a2
    assert (await graph.get_memory(b1))["replaced_by"] == b2


# ---- vetoed pairs are kept as-is ----


@pytest.mark.asyncio
async def test_profile_referenced_pair_kept(graph, vector, embedder):
    """A pair the profile guards exempt (high confidence ≥ threshold) is
    never merged — both memories stay latest."""
    await _seed(graph, vector, embedder, "用户住在北京", confidence=0.9)
    await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4)

    count = await make_engine(graph, vector).consolidate_duplicates("e1")
    assert count == 0

    candidates = await graph.list_latest_memories("e1")
    assert len(candidates) == 2


@pytest.mark.asyncio
async def test_updates_edge_pair_kept(graph, vector, embedder):
    """A pair joined by an UPDATES edge is a timeline step — both survive."""
    a = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4)
    b = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4)
    await graph.create_relationship(a, b, "UPDATES")

    count = await make_engine(graph, vector).consolidate_duplicates("e1")
    assert count == 0
    assert (await graph.get_memory(a))["is_latest"] is True
    assert (await graph.get_memory(b))["is_latest"] is True


@pytest.mark.asyncio
async def test_veto_inside_group_splits_merge(graph, vector, embedder):
    """A three-member group where the outer pair is vetoed by an UPDATES
    edge: the middle member merges into the representative, the vetoed
    outer member survives untouched."""
    a = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=0)
    b = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=1)
    c = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=2)
    await graph.create_relationship(a, c, "UPDATES")

    count = await make_engine(graph, vector).consolidate_duplicates("e1")
    assert count == 1

    # Newest (a) is the representative; b merges into it.
    assert (await graph.get_memory(a))["is_latest"] is True
    assert (await graph.get_memory(b))["is_latest"] is False
    assert (await graph.get_memory(b))["replaced_by"] == a
    # The UPDATES-vetoed member survives.
    assert (await graph.get_memory(c))["is_latest"] is True
    assert (await graph.get_memory(c))["replaced_by"] is None


# ---- isolation, empty graphs, scope ----


@pytest.mark.asyncio
async def test_entity_scoped_run_does_not_touch_others(graph, vector, embedder):
    mine_a = await _seed(graph, vector, embedder, "用户住在北京", entity_id="e1", days_old=1)
    mine_b = await _seed(graph, vector, embedder, "用户住在北京", entity_id="e1")
    theirs_a = await _seed(graph, vector, embedder, "用户住在北京", entity_id="e2", days_old=1)
    theirs_b = await _seed(graph, vector, embedder, "用户住在北京", entity_id="e2")

    assert await make_engine(graph, vector).consolidate_duplicates("e1") == 1
    assert (await graph.get_memory(mine_b))["is_latest"] is True
    assert (await graph.get_memory(mine_a))["is_latest"] is False
    for mid in (theirs_a, theirs_b):
        assert (await graph.get_memory(mid))["is_latest"] is True

    assert await make_engine(graph, vector).consolidate_duplicates() == 1
    assert (await graph.get_memory(theirs_b))["is_latest"] is True
    assert (await graph.get_memory(theirs_a))["is_latest"] is False


@pytest.mark.asyncio
async def test_empty_and_single_memory_graphs_have_zero_side_effects(graph, vector, embedder):
    engine = make_engine(graph, vector)
    assert await engine.consolidate_duplicates("ghost") == 0
    assert await engine.consolidate_duplicates() == 0

    sole = await _seed(graph, vector, embedder, "用户住在北京")
    assert await engine.consolidate_duplicates("e1") == 0
    # The single memory is untouched — no merge can happen without a pair.
    assert (await graph.get_memory(sole))["is_latest"] is True
    assert (await graph.get_memory(sole)).get("replaced_by") is None


# ---- observability: metrics per decision ----


@pytest.mark.asyncio
async def test_metrics_count_decisions_by_action(graph, vector, embedder):
    """Every pair verdict increments the counter once with its action
    label — all five engine-reachable labels asserted positively (``keep``
    is defense-in-depth only: the per-entity detector never emits it)."""
    # consolidate pair
    await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4)
    await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4)
    # profile-exempt pair (high confidence ≥ threshold)
    await _seed(graph, vector, embedder, "用户喜欢喝咖啡", confidence=0.9)
    await _seed(graph, vector, embedder, "用户喜欢喝咖啡", confidence=0.4)
    # type-exempt pair
    await _seed(graph, vector, embedder, "用户住在上海", memory_type="fact", confidence=0.4)
    await _seed(
        graph, vector, embedder, "用户住在上海", memory_type="preference", confidence=0.4
    )
    # contradiction pair: rule layer classifies 搬到 as UPDATES — the
    # deterministic stand-in for a high-similarity paraphrase (same
    # forced vector as the T1 detector tests)
    a = await _seed(graph, vector, embedder, "用户住在广州", confidence=0.4)
    b = await _seed(graph, vector, embedder, "用户搬到深圳", confidence=0.4)
    forced = (await embedder.embed(["用户住在广州"]))[0]
    await vector.store(a, "用户住在广州", forced, entity_id="e1")
    await vector.store(b, "用户搬到深圳", forced, entity_id="e1")
    # updates-edge pair: identical contents joined by a temporal chain
    c = await _seed(graph, vector, embedder, "用户喜欢喝茶", confidence=0.4)
    d = await _seed(graph, vector, embedder, "用户喜欢喝茶", confidence=0.4)
    await graph.create_relationship(c, d, "UPDATES")

    before = {
        act: _counter(act)
        for act in (
            "consolidated",
            "keep",
            "exempt_profile",
            "exempt_type",
            "exempt_contradiction",
            "exempt_updates",
        )
    }
    await make_engine(graph, vector).consolidate_duplicates("e1")

    assert _counter("consolidated") == before["consolidated"] + 1
    assert _counter("exempt_profile") == before["exempt_profile"] + 1
    assert _counter("exempt_type") == before["exempt_type"] + 1
    assert _counter("exempt_contradiction") == before["exempt_contradiction"] + 1
    assert _counter("exempt_updates") == before["exempt_updates"] + 1
    assert _counter("keep") == before["keep"]


@pytest.mark.asyncio
async def test_no_verdicts_no_metric_increments(graph, vector, embedder):
    before = _counter("consolidated")
    await _seed(graph, vector, embedder, "用户住在北京")
    await make_engine(graph, vector).consolidate_duplicates("e1")
    assert _counter("consolidated") == before


# ---- failure isolation ----


@pytest.mark.asyncio
async def test_single_failing_memory_does_not_abort_entity(graph, vector, embedder, monkeypatch):
    first = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=30)
    second = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=15)
    third = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=0)

    original = GraphStore.mark_consolidated

    async def _broken(self, memory_id, representative_id, reason="consolidated"):
        if memory_id == first:
            raise RuntimeError("boom")
        return await original(self, memory_id, representative_id, reason=reason)

    monkeypatch.setattr(GraphStore, "mark_consolidated", _broken)

    count = await make_engine(graph, vector).consolidate_duplicates("e1")
    # second and third still merge into third; first fails.
    assert count == 1
    assert (await graph.get_memory(first))["is_latest"] is True
    assert (await graph.get_memory(second))["is_latest"] is False
    assert (await graph.get_memory(third))["is_latest"] is True


@pytest.mark.asyncio
async def test_broken_entity_does_not_abort_sweep(graph, vector, embedder, monkeypatch):
    # Distinct ages (not a same-timestamp pair) — the representative
    # choice must be deterministic, not UUID-order dependent.
    await _seed(graph, vector, embedder, "用户住在北京", entity_id="e1", confidence=0.4, days_old=30)
    b = await _seed(graph, vector, embedder, "用户住在北京", entity_id="e1", confidence=0.4)
    await _seed(graph, vector, embedder, "用户喜欢喝咖啡", entity_id="e2", confidence=0.4)
    d = await _seed(graph, vector, embedder, "用户喜欢喝咖啡", entity_id="e2", confidence=0.4)

    original = DuplicatesDetector.detect

    async def _broken(self, entity_id, *, now=None):
        if entity_id == "e2":
            raise RuntimeError("boom")
        return await original(self, entity_id, now=now)

    monkeypatch.setattr(DuplicatesDetector, "detect", _broken)

    count = await make_engine(graph, vector).consolidate_duplicates()
    # e1's pair still consolidates; e2 is logged and skipped.
    assert count == 1
    assert (await graph.get_memory(b))["is_latest"] is True
    for mid in (d,):
        assert (await graph.get_memory(mid))["is_latest"] is True


# ---- determinism and idempotency ----


@pytest.mark.asyncio
async def test_second_run_finds_nothing_left(graph, vector, embedder):
    """Consolidation is idempotent: after the first run the graph is
    stable and a second run merges nothing more."""
    await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=30)
    await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=0)
    await _seed(graph, vector, embedder, "用户喜欢喝咖啡", confidence=0.4, days_old=10)
    await _seed(graph, vector, embedder, "用户喜欢喝咖啡", confidence=0.4, days_old=1)

    engine = make_engine(graph, vector)
    assert await engine.consolidate_duplicates("e1") == 2
    assert await engine.consolidate_duplicates("e1") == 0

    latest = await graph.list_latest_memories("e1")
    assert len(latest) == 2


@pytest.mark.asyncio
async def test_identical_entities_decide_identically(graph, vector, embedder):
    """Structurally identical entities yield identical outcomes."""
    for eid in ("e1", "e2"):
        await _seed(graph, vector, embedder, "用户住在北京", entity_id=eid, days_old=5)
        await _seed(graph, vector, embedder, "用户住在北京", entity_id=eid)
        await _seed(graph, vector, embedder, "用户喜欢喝咖啡", entity_id=eid)

    engine = make_engine(graph, vector)
    first = await engine.consolidate_duplicates("e1")
    second = await engine.consolidate_duplicates("e2")
    assert first == second == 1
