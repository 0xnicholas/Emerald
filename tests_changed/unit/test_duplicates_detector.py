"""Detector-level tests for B6 duplicate detection + veto guardrails (T1, #42).

The seam under test is ``DuplicatesDetector.detect`` on the in-memory
graph + vector stores with the deterministic mock embedder: candidate
generation (vector similarity is only the optimization layer), the
veto matrix end-to-end (entity isolation / history / UPDATES edge /
contradiction / profile protection), representative convergence, the
per-entity scale cap, and determinism (same graph + same explicit now
→ same verdicts).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from emerald.core.duplicates import (
    DuplicateAction,
    DuplicateConfig,
    DuplicatesDetector,
)
from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.graph import GraphStore
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


def make_detector(
    graph: GraphStore,
    vector: VectorStore,
    config: DuplicateConfig | None = None,
) -> DuplicatesDetector:
    return DuplicatesDetector(graph=graph, vector=vector, config=config)


async def _seed(
    graph: GraphStore,
    vector: VectorStore,
    embedder: MockEmbeddingProvider,
    content: str,
    *,
    entity_id: str = "e1",
    memory_type: str = "fact",
    confidence: float = 0.8,
    days_old: int = 0,
) -> str:
    """Create a memory, backdate it, and index it into the vector store —
    the same record a pipeline ingest would produce."""
    mid = await graph.create_memory(
        content, entity_id=entity_id, memory_type=memory_type, confidence=confidence
    )
    memory = await graph.get_memory(mid)
    memory["created_at"] = NOW - timedelta(days=days_old)
    embedding = (await embedder.embed([content]))[0]
    await vector.store(mid, content, embedding, entity_id=entity_id)
    return mid


# ---- candidate generation + convergence ----


@pytest.mark.asyncio
async def test_identical_pair_consolidates_into_newest(graph, vector, embedder):
    """Two identical restatements converge; the representative is the
    newer memory (created_at desc after the trust tie). Confidence is
    below the profile static threshold so neither memory is exempt."""
    older = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=30)
    newer = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=0)

    verdicts = await make_detector(graph, vector).detect("e1", now=NOW)
    assert len(verdicts) == 1

    verdict = verdicts[0]
    assert set(verdict.candidate.ids) == {older, newer}
    assert verdict.candidate.similarity == pytest.approx(1.0)  # identical mock embeddings
    assert verdict.action is DuplicateAction.CONSOLIDATE
    assert verdict.representative_id == newer


@pytest.mark.asyncio
async def test_triple_converges_on_single_representative(graph, vector, embedder):
    """A duplicate group of three produces pairwise verdicts that all
    point at the same representative."""
    await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=30)
    mid = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=15)
    newest = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=0)

    verdicts = await make_detector(graph, vector).detect("e1", now=NOW)
    assert len(verdicts) == 3
    assert all(v.action is DuplicateAction.CONSOLIDATE for v in verdicts)
    # Pairwise convergence: every verdict's representative is the newer
    # member of its pair; the group maximum (newest) is the representative
    # of every pair it takes part in. T3 (#44) reduces these to the group
    # representative via select_representative.
    assert {v.representative_id for v in verdicts} == {mid, newest}


@pytest.mark.asyncio
async def test_empty_and_single_memory_graphs_have_no_verdicts(graph, vector, embedder):
    assert await make_detector(graph, vector).detect("e1", now=NOW) == []

    await _seed(graph, vector, embedder, "用户住在北京")
    assert await make_detector(graph, vector).detect("e1", now=NOW) == []


@pytest.mark.asyncio
async def test_unrelated_memories_are_not_candidates(graph, vector, embedder):
    """Different contents (different mock embeddings) fall below the
    similarity threshold — vector similarity only generates candidates
    at/above the threshold."""
    await _seed(graph, vector, embedder, "用户住在北京")
    await _seed(graph, vector, embedder, "用户喜欢喝咖啡")
    assert await make_detector(graph, vector).detect("e1", now=NOW) == []


@pytest.mark.asyncio
async def test_similarity_threshold_is_configurable(graph, vector, embedder):
    """The threshold is the D2 calibration seam: a 0.6-cosine pair is no
    candidate at the default 0.9, and is one at 0.5."""
    a = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4)
    b = await _seed(graph, vector, embedder, "用户喜欢喝咖啡", confidence=0.4)
    # Override the stored embeddings with controlled vectors: cosine 0.6.
    await vector.store(a, "用户住在北京", [1.0, 0.0, 0.0], entity_id="e1")
    await vector.store(b, "用户喜欢喝咖啡", [0.6, 0.8, 0.0], entity_id="e1")

    assert await make_detector(graph, vector).detect("e1", now=NOW) == []

    verdicts = await make_detector(graph, vector, DuplicateConfig(similarity_threshold=0.5)).detect(
        "e1", now=NOW
    )
    assert len(verdicts) == 1
    assert verdicts[0].candidate.similarity == pytest.approx(0.6)
    assert verdicts[0].action is DuplicateAction.CONSOLIDATE


# ---- the veto matrix end-to-end ----


@pytest.mark.asyncio
async def test_cross_entity_isolation(graph, vector, embedder):
    """Identical content in another entity never appears in this entity's
    candidate pairs (ADR-0002)."""
    a = await _seed(graph, vector, embedder, "用户住在北京", entity_id="e1")
    b = await _seed(graph, vector, embedder, "用户住在北京", entity_id="e1")
    await _seed(graph, vector, embedder, "用户住在北京", entity_id="e2")

    verdicts = await make_detector(graph, vector).detect("e1", now=NOW)
    assert len(verdicts) == 1
    assert set(verdicts[0].candidate.ids) == {a, b}

    assert await make_detector(graph, vector).detect("e2", now=NOW) == []


@pytest.mark.asyncio
async def test_archived_memory_never_participates(graph, vector, embedder):
    """History (is_latest=false) is not a candidate: only latest memories
    are loaded, so an archived twin leaves nothing to merge."""
    a = await _seed(graph, vector, embedder, "用户住在北京", days_old=30)
    await _seed(graph, vector, embedder, "用户住在北京", days_old=0)
    await graph.update_is_latest(a, False, replaced_by="some_other")

    assert await make_detector(graph, vector).detect("e1", now=NOW) == []


@pytest.mark.asyncio
async def test_updates_edge_vetoes_pair(graph, vector, embedder):
    """An existing UPDATES relationship marks a temporal chain — the pair
    is exempt even though the contents are identical."""
    a = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4)
    b = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4)
    await graph.create_relationship(a, b, "UPDATES")

    verdicts = await make_detector(graph, vector).detect("e1", now=NOW)
    assert len(verdicts) == 1
    assert verdicts[0].action is DuplicateAction.EXEMPT_UPDATES
    assert verdicts[0].reason == "updates_edge"


@pytest.mark.asyncio
async def test_contradiction_pair_vetoed(graph, vector, embedder):
    """A pair the relationship rules classify as UPDATES (搬到 marks the
    old fact replaced) is never merged. The mock embedder only makes
    identical strings similar, so the stored embeddings are forced to
    the same vector — the deterministic stand-in for a high-similarity
    paraphrase (spec #41: real paraphrase recall is a D2 calibration
    item). Vector similarity only generates the candidate; the rule
    vetoes it."""
    a = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4)
    b = await _seed(graph, vector, embedder, "用户搬到上海", confidence=0.4)
    forced = (await embedder.embed(["用户住在北京"]))[0]
    await vector.store(a, "用户住在北京", forced, entity_id="e1")
    await vector.store(b, "用户搬到上海", forced, entity_id="e1")

    verdicts = await make_detector(graph, vector).detect("e1", now=NOW)
    assert len(verdicts) == 1
    assert verdicts[0].candidate.similarity == pytest.approx(1.0)
    assert verdicts[0].action is DuplicateAction.EXEMPT_CONTRADICTION
    assert verdicts[0].reason == "contradiction"


@pytest.mark.asyncio
async def test_cross_type_pair_vetoed(graph, vector, embedder):
    await _seed(graph, vector, embedder, "用户住在北京", memory_type="fact")
    await _seed(graph, vector, embedder, "用户住在北京", memory_type="preference")

    verdicts = await make_detector(graph, vector).detect("e1", now=NOW)
    assert len(verdicts) == 1
    assert verdicts[0].action is DuplicateAction.EXEMPT_TYPE


@pytest.mark.asyncio
async def test_profile_referenced_pair_exempt(graph, vector, embedder):
    """A memory the entity profile references is exempt through the shared
    is_protected single point: high-confidence fact (static profile
    fact) + low-confidence twin are both kept."""
    await _seed(graph, vector, embedder, "用户住在北京", confidence=0.9)
    await _seed(graph, vector, embedder, "用户住在北京", confidence=0.3)

    verdicts = await make_detector(graph, vector).detect("e1", now=NOW)
    assert len(verdicts) == 1
    assert verdicts[0].action is DuplicateAction.EXEMPT_PROFILE
    assert verdicts[0].reason == "protected"


@pytest.mark.asyncio
async def test_dynamic_profile_fact_pair_exempt(graph, vector, embedder):
    """A recent high-confidence episodic memory is a dynamic profile fact
    (within the lookback window) — also protected."""
    await _seed(
        graph,
        vector,
        embedder,
        "用户昨天去了长城",
        memory_type="episodic",
        confidence=0.9,
        days_old=1,
    )
    await _seed(
        graph,
        vector,
        embedder,
        "用户昨天去了长城",
        memory_type="episodic",
        confidence=0.2,
        days_old=1,
    )

    verdicts = await make_detector(graph, vector).detect("e1", now=NOW)
    assert len(verdicts) == 1
    assert verdicts[0].action is DuplicateAction.EXEMPT_PROFILE


@pytest.mark.asyncio
async def test_rag_chunks_never_become_candidates(graph, vector, embedder):
    """RAG document chunks share the vector store but are excluded from
    the candidate pool by the memory-only search filter — a document
    chunk with an identical embedding to a memory never pairs with it."""
    a = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4)
    b = await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4)
    forced = (await embedder.embed(["用户住在北京"]))[0]
    await vector.store("doc-chunk-1", "用户住在北京", forced, entity_id="e1", document_id="doc-1")

    verdicts = await make_detector(graph, vector).detect("e1", now=NOW)
    assert len(verdicts) == 1
    assert set(verdicts[0].candidate.ids) == {a, b}


# ---- scale guard + determinism ----


@pytest.mark.asyncio
async def test_memory_cap_bounds_candidate_pool(graph, vector, embedder):
    """The per-entity scale guard caps the latest-memory pool (newest
    first): with max_memories=2 and three identical memories, only the
    newest two can pair up."""
    await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=30)
    await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=15)
    await _seed(graph, vector, embedder, "用户住在北京", confidence=0.4, days_old=0)

    verdicts = await make_detector(graph, vector, DuplicateConfig(max_memories=2)).detect(
        "e1", now=NOW
    )
    assert len(verdicts) == 1
    assert verdicts[0].action is DuplicateAction.CONSOLIDATE


@pytest.mark.asyncio
async def test_detect_is_deterministic(graph, vector, embedder):
    """Same graph + same explicit now → identical verdicts on every run."""
    await _seed(graph, vector, embedder, "用户住在北京", confidence=0.9, days_old=10)
    await _seed(graph, vector, embedder, "用户住在北京", confidence=0.7, days_old=5)
    await _seed(graph, vector, embedder, "用户住在北京", confidence=0.5, days_old=0)
    await _seed(graph, vector, embedder, "用户喜欢喝咖啡")

    detector = make_detector(graph, vector)
    first = await detector.detect("e1", now=NOW)
    second = await detector.detect("e1", now=NOW)

    assert first == second
    ids = [v.candidate.ids for v in first]
    assert ids == sorted(ids)
