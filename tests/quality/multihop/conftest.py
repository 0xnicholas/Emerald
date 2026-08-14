"""Fixtures for the multihop quality suite (B4, tickets #30-#34).

Reuses the mention suite's deterministic engine (corpus gazetteer +
rule-only extraction + mock embeddings) so the two sections share one
deterministic world: mentions resolve exactly as section 4 asserts, and
the multihop sections consume that resolution through search.

``make_orchestrator`` is the shared SearchOrchestrator builder for all
five multihop files — one seam, one result-shaping code path.
"""

from __future__ import annotations

import pytest

from emerald.core.search import SearchOrchestrator
from tests.quality.mentions.conftest import add_content, make_engine

__all__ = ["add_content", "engine", "make_engine", "make_orchestrator"]


@pytest.fixture
def engine():
    """MemoryEngine on the rule-only path with the corpus gazetteer."""
    return make_engine()


def make_orchestrator(engine) -> SearchOrchestrator:
    """SearchOrchestrator wired to the deterministic rule-only engine."""
    return SearchOrchestrator(
        graph=engine.graph,
        vector=engine.vector,
        fast_lane_store=engine.fast_lane_store,
        embedder=engine.embedder,
    )
