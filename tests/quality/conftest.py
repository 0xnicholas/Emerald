"""Shared fixtures for the independent quality suites (ADR-0001).

Suites:
- temporal correctness (ticket #9)
- forgetting effectiveness (ticket #10)
- graph relationship precision (ticket #11)
- mention precision / resolution / taxonomy / isolation (B3)
- multihop retrieval (B4)
- community forgetting effectiveness (B5, ticket #40)

Principles (roadmap M2 / Wayfinder map #8):
- deterministic corpus + fixed semantics (no wall-clock dependence)
- mock embeddings (MockEmbeddingProvider)
- rule-only path (use_llm=False) — the LLM path is covered by the
  absolute-score report instead
- real-storage variants (Neo4j) when a test backend is reachable;
  they skip otherwise so the aggregate CI gate stays green
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from emerald.core.chunker import ChunkerRegistry
from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.engine import MemoryEngine
from emerald.core.extractor import ExtractorRegistry
from emerald.core.graph import GraphStore
from emerald.core.relationship import RelationshipEngine
from emerald.core.vector import VectorStore
from emerald.pipeline.chunking.text import TextChunker
from emerald.pipeline.extraction.text import TextExtractor

NEO4J_URI = os.environ.get("EMERALD_TEST_NEO4J_URI", "bolt://localhost:7688")
NEO4J_USER = os.environ.get("EMERALD_TEST_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("EMERALD_TEST_NEO4J_PASSWORD", "emerald_dev")

# Entity prefix reserved for the quality suites; cleanup targets these.
QUALITY_ENTITY_PREFIX = "user_quality_"


def now_utc() -> datetime:
    return datetime.now(UTC)


def days_ago(days: int) -> datetime:
    return now_utc() - timedelta(days=days)


def days_ahead(days: int) -> datetime:
    return now_utc() + timedelta(days=days)


@pytest.fixture
def entity_id() -> str:
    return f"{QUALITY_ENTITY_PREFIX}{uuid.uuid4().hex[:8]}"


@pytest.fixture
def graph():
    return GraphStore(use_db=False)


@pytest.fixture
def engine():
    """MemoryEngine on the rule-only path: use_llm=False everywhere.

    Deterministic: mock embedder + no LLM calls (no API keys required).
    """
    extractors = ExtractorRegistry()
    extractors.register("text", TextExtractor())
    chunkers = ChunkerRegistry()
    chunkers.register("text", TextChunker())
    graph = GraphStore(use_db=False)
    vector = VectorStore(use_db=False)
    relationships = RelationshipEngine(
        graph=graph, vector=vector, use_llm=False,
    )
    return MemoryEngine(
        extractor_registry=extractors,
        chunker_registry=chunkers,
        embedder=MockEmbeddingProvider(dimension=128),
        graph=graph,
        vector=vector,
        relationships=relationships,
        use_db=False,
    )


async def backdate(graph: GraphStore, entity_id: str, memory_id: str, days: int) -> None:
    """Rewind a memory's created_at for deterministic age-based scenarios."""
    for m in graph._memories.get(entity_id, []):
        if m["id"] == memory_id:
            m["created_at"] = days_ago(days)
            return


async def set_valid_until(
    graph: GraphStore, entity_id: str, memory_id: str, when: datetime,
) -> None:
    """Override a memory's valid_until deterministically."""
    for m in graph._memories.get(entity_id, []):
        if m["id"] == memory_id:
            m["valid_until"] = when
            return


def memory_id_by_content(
    graph: GraphStore, entity_id: str, content: str,
) -> str | None:
    """Find the memory id whose content equals ``content``."""
    for m in graph._memories.get(entity_id, []):
        if m["content"] == content:
            return m["id"]
    return None


@pytest.fixture(scope="module")
def neo4j_available():
    """Skip the module if the test Neo4j backend is not reachable."""
    import asyncio

    from neo4j import AsyncGraphDatabase

    async def _check():
        try:
            driver = AsyncGraphDatabase.driver(
                NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD),
            )
            await driver.verify_connectivity()
            await driver.close()
            return True
        except Exception:
            return False

    if not asyncio.run(_check()):
        pytest.skip(
            f"Test Neo4j not reachable at {NEO4J_URI}", allow_module_level=True,
        )


@pytest.fixture
async def neo4j_driver(neo4j_available):
    """Yield an initialized Neo4j driver; clean up quality entities after."""
    from neo4j import AsyncGraphDatabase

    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    await driver.verify_connectivity()

    import emerald.db.neo4j as neo4j_mod

    original = neo4j_mod.get_neo4j_driver
    neo4j_mod.get_neo4j_driver = lambda: driver
    neo4j_mod._driver = driver

    yield driver

    async with driver.session() as session:
        await session.run(
            "MATCH (m:Memory) WHERE m.entity_id STARTS WITH $prefix "
            "DETACH DELETE m",
            prefix=QUALITY_ENTITY_PREFIX,
        )
        await session.run(
            "MATCH (mn:Mention) WHERE mn.entity_id STARTS WITH $prefix "
            "DETACH DELETE mn",
            prefix=QUALITY_ENTITY_PREFIX,
        )
        await session.run(
            "MATCH (e:Entity) WHERE e.id STARTS WITH $prefix DETACH DELETE e",
            prefix=QUALITY_ENTITY_PREFIX,
        )

    await driver.close()
    neo4j_mod.get_neo4j_driver = original
    neo4j_mod._driver = None
