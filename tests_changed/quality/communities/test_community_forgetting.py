"""Quality suite section 6 — community forgetting effectiveness (ADR-0001, ticket #40).

Guards the forgetting effectiveness of the B5 community-forgetting
strategy (spec #36): a deterministic corpus of two expired communities +
an active community + a bridge memory + a profile-referenced signal is
forgotten through the rule path (no LLM) with mock embeddings and
backdated timestamps, and the outcome must meet three thresholds:

- community elimination rate >= 0.95 (expired communities gone as clusters)
- signal survival rate       >= 0.98 (active/bridge/profile signals kept)
- retrieval retention rate   >= 0.95 (surviving signals still searchable)

Retrieval sets before and after forgetting are asserted exactly — only
the expired communities disappear, every signal stays retrievable.

The same scenario re-runs on real storage in
test_neo4j_community_variants.py (skipped when no test Neo4j is
reachable); the CI `quality-temporal` job covers both backends.
"""

from __future__ import annotations

import uuid
from functools import partial

import pytest

from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.vector import VectorStore
from tests.quality.communities.scenario import (
    make_orchestrator,
    run_community_forgetting,
    seed_community_corpus,
)
from tests.quality.conftest import backdate

pytestmark = [pytest.mark.quality]


@pytest.mark.asyncio
async def test_community_forgetting_metrics(graph) -> None:
    """Aggregate gate: all three metrics across the community scenario."""
    vector = VectorStore(use_db=False)
    embedder = MockEmbeddingProvider(dimension=128)
    entity_id = f"user_quality_community_{uuid.uuid4().hex[:8]}"

    corpus = await seed_community_corpus(
        graph,
        vector,
        embedder,
        entity_id,
        backdate=partial(backdate, graph, entity_id),
    )
    orchestrator = make_orchestrator(graph, vector, embedder)
    result = await run_community_forgetting(graph, orchestrator, corpus)

    result.elimination.assert_threshold()
    result.survival.assert_threshold()
    result.retrieval.assert_threshold()

    print(
        f"\n[community-forgetting] elimination={result.elimination.rate:.3f} "
        f"survival={result.survival.rate:.3f} "
        f"retrieval={result.retrieval.rate:.3f} "
        f"forgotten={len(result.forgotten)} survivors={len(result.survivors)}"
    )
