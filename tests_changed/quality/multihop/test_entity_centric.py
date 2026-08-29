"""Quality suite section 5 — multihop retrieval (B4, ticket #30).

B4 T1 asserts, on the deterministic rule-only path:

- ``search(about=<canonical>)`` returns every memory in the entity's pool
  that mentions the thing, across all surface forms (Google / 谷歌 /
  GOOGLE resolve to one canonical node — B3 T2 semantics)
- a memory with zero matches (unknown canonical, no mentions) yields an
  empty result set, not an error
- entity isolation: about retrieval never crosses entity boundaries
- about is a memory-graph operation: results are memories only (no RAG)

Deterministic labelled corpus + mock embeddings + rule-only path, same
fixtures as section 4 (mentions); the engine fixture reuses the corpus
gazetteer so extraction is exactly the labelled mentions.
"""

from __future__ import annotations

import pytest

from emerald.core.search import SearchMode
from tests.quality.mentions.conftest import add_content
from tests.quality.mentions.corpus import HAPPY_PATH_CORPUS
from tests.quality.multihop.conftest import make_orchestrator

pytestmark = [pytest.mark.quality]

# Corpus entries: (content, expected mentions).
PYTHON_ENTRY = HAPPY_PATH_CORPUS[0]  # "用户用 Python 写数据管线" → Python
GOOGLE_ENTRY = HAPPY_PATH_CORPUS[1]  # "用户在 Google 工作" → Google
GUGE_ENTRY = HAPPY_PATH_CORPUS[8]  # "用户在谷歌工作" → Google
UPPER_GOOGLE_ENTRY = HAPPY_PATH_CORPUS[9]  # "用户在 GOOGLE 工作" → Google
BOTH_ENTRY = HAPPY_PATH_CORPUS[4]  # Python + Google in one memory
NO_MENTION_ENTRY = HAPPY_PATH_CORPUS[6]  # "用户喜欢喝咖啡" → []



async def test_about_returns_all_surface_forms_of_the_mention(engine, entity_id):
    """about=Google returns the Google/谷歌/GOOGLE memories, not others."""
    google_mid = await add_content(engine, entity_id, GOOGLE_ENTRY[0])
    guge_mid = await add_content(engine, entity_id, GUGE_ENTRY[0])
    upper_mid = await add_content(engine, entity_id, UPPER_GOOGLE_ENTRY[0])
    both_mid = await add_content(engine, entity_id, BOTH_ENTRY[0])
    python_mid = await add_content(engine, entity_id, PYTHON_ENTRY[0])

    results = await make_orchestrator(engine).search(
        "关于 Google 的一切",
        entity_id=entity_id,
        search_mode=SearchMode.MEMORY,
        about="Google",
    )
    ids = {r.id for r in results.results}
    assert ids == {google_mid, guge_mid, upper_mid, both_mid}
    assert python_mid not in ids


async def test_about_unknown_canonical_returns_empty(engine, entity_id):
    """An unknown canonical form yields an empty result set, not an error."""
    await add_content(engine, entity_id, GOOGLE_ENTRY[0])
    await add_content(engine, entity_id, NO_MENTION_ENTRY[0])

    results = await make_orchestrator(engine).search(
        "关于 NoSuchThing 的一切",
        entity_id=entity_id,
        search_mode=SearchMode.MEMORY,
        about="NoSuchThing",
    )
    assert results.results == []


async def test_about_is_entity_scoped(engine, entity_id):
    """Entity A's about never surfaces entity B's memories."""
    other_entity = f"{entity_id}_other"
    mid_a = await add_content(engine, entity_id, GOOGLE_ENTRY[0])
    mid_b = await add_content(engine, other_entity, GOOGLE_ENTRY[0])

    results = await make_orchestrator(engine).search(
        "Google", entity_id=entity_id, search_mode=SearchMode.MEMORY, about="Google",
    )
    ids = {r.id for r in results.results}
    assert ids == {mid_a}
    assert mid_b not in ids


async def test_about_returns_memory_source_only(engine, entity_id):
    """about is a memory-graph operation: no RAG results leak in."""
    mid = await add_content(engine, entity_id, GOOGLE_ENTRY[0])
    await engine.vector.store(
        "rag-doc-1", "在 Google 工作的文档", [0.1] * 128,
        entity_id=entity_id, document_id="doc-1",
    )

    results = await make_orchestrator(engine).search(
        "Google", entity_id=entity_id, search_mode=SearchMode.HYBRID, about="Google",
    )
    assert all(r.source == "memory" for r in results.results)
    assert {r.id for r in results.results} == {mid}
