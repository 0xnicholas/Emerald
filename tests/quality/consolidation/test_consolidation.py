"""Quality suite section 7 — consolidation effectiveness (ADR-0001, ticket #45).

Guards the consolidation effectiveness of the B6 duplicate-consolidation
strategy (spec #41): a deterministic corpus of three duplicate groups
(identical restatements at different ages and confidence — the
deterministic stand-in for near-duplicate facts; real paraphrase recall
is a D2 calibration item) + the full veto-guardrail counter-example set
(profile-protected / contradiction / cross-type / UPDATES-edge pairs) +
unrelated signal memories is consolidated through the rule path (no LLM)
with mock embeddings and backdated timestamps, and the outcome must meet
three thresholds:

- consolidation recall rate >= 0.95 (duplicate groups converge to one
  representative)
- mis-merge rate          == 1.0 (HARD GATE: 误并率 = 0 — a mis-merge
  is silent information loss, no threshold tolerance)
- retrieval retention rate >= 0.95 (surviving signals still searchable)

Retrieval sets before and after consolidation are asserted exactly by
memory id — duplicate groups share identical content, so members are
distinguished by id, never by content: representatives and every
survivor stay retrievable, merged members vanish.

The same scenario re-runs on real storage in
test_neo4j_consolidation_variants.py (skipped when no test Neo4j is
reachable); the CI `quality-temporal` job covers both backends.
"""

from __future__ import annotations

import uuid
from functools import partial

import pytest

from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.vector import VectorStore
from tests.quality.conftest import backdate
from tests.quality.consolidation.scenario import (
    make_orchestrator,
    run_consolidation,
    seed_consolidation_corpus,
)

pytestmark = [pytest.mark.quality]


@pytest.mark.asyncio
async def test_consolidation_metrics(graph) -> None:
    """Aggregate gate: all three metrics across the consolidation scenario."""
    vector = VectorStore(use_db=False)
    embedder = MockEmbeddingProvider(dimension=128)
    entity_id = f"user_quality_consolidation_{uuid.uuid4().hex[:8]}"

    corpus = await seed_consolidation_corpus(
        graph,
        vector,
        embedder,
        entity_id,
        backdate=partial(backdate, graph, entity_id),
    )
    orchestrator = make_orchestrator(graph, vector, embedder)
    result = await run_consolidation(graph, vector, orchestrator, corpus)

    result.recall.assert_threshold()
    result.mis_merge.assert_threshold()
    result.retrieval.assert_threshold()

    print(
        f"\n[consolidation] recall={result.recall.rate:.3f} "
        f"mis_merge={result.mis_merge.rate:.3f} "
        f"retention={result.retrieval.rate:.3f} "
        f"merged={len(result.merged)} survivors={len(result.survivors)}"
    )
