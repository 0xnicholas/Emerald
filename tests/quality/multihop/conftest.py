"""Fixtures for the multihop quality suite (B4, tickets #30-#34).

Reuses the mention suite's deterministic engine (corpus gazetteer +
rule-only extraction + mock embeddings) so the two sections share one
deterministic world: mentions resolve exactly as section 4 asserts, and
the multihop sections consume that resolution through search.
"""

from __future__ import annotations

import pytest

from tests.quality.mentions.conftest import add_content, make_engine

__all__ = ["add_content", "engine", "make_engine"]


@pytest.fixture
def engine():
    """MemoryEngine on the rule-only path with the corpus gazetteer."""
    return make_engine()
