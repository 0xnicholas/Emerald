"""Fixtures for the mention-precision quality suites (B3, tickets #22-#24).

Mirrors the shared quality engine fixture (tests/quality/conftest.py) but
injects the labelled corpus's gazetteer, so the rule/mock extraction path
deterministically produces exactly the corpus's mentions — no LLM.

``make_engine`` lets individual tests vary the gazetteer (invalid-type
fallback, #24) or the rule-path confidence (confidence gating, #24) while
keeping everything else deterministic.
"""

from __future__ import annotations

import pytest

from emerald.core.chunker import ChunkerRegistry
from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.engine import MemoryEngine
from emerald.core.extractor import ExtractorRegistry
from emerald.core.graph import GraphStore
from emerald.core.mentions import RuleMentionExtractor
from emerald.core.relationship import RelationshipEngine
from emerald.core.vector import VectorStore
from emerald.pipeline.chunking.text import TextChunker
from emerald.pipeline.extraction.text import TextExtractor
from tests.quality.mentions.corpus import CORPUS_GAZETTEER


def make_engine(
    gazetteer: dict[str, tuple[str, str]] | None = None,
    confidence: float = 0.9,
) -> MemoryEngine:
    """MemoryEngine on the rule-only path with a caller-chosen gazetteer.

    Deterministic: mock embedder, no LLM calls, corpus-scoped mentions.
    """
    extractors = ExtractorRegistry()
    extractors.register("text", TextExtractor())
    chunkers = ChunkerRegistry()
    chunkers.register(
        "text",
        TextChunker(
            mention_extractor=RuleMentionExtractor(
                known_entities=gazetteer or CORPUS_GAZETTEER,
                confidence=confidence,
            ),
        ),
    )
    graph = GraphStore(use_db=False)
    vector = VectorStore(use_db=False)
    relationships = RelationshipEngine(graph=graph, vector=vector, use_llm=False)
    return MemoryEngine(
        extractor_registry=extractors,
        chunker_registry=chunkers,
        embedder=MockEmbeddingProvider(dimension=128),
        graph=graph,
        vector=vector,
        relationships=relationships,
        use_db=False,
    )


@pytest.fixture
def engine():
    """MemoryEngine on the rule-only path with the corpus gazetteer."""
    return make_engine()
