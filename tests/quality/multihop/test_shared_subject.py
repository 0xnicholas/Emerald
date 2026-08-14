"""Quality suite section 5b — shared-subject bridging (B4, ticket #31).

B4 T2 asserts, on the deterministic rule-only path:

- ``search(depth>=1)`` bridges memories that mention the same canonical
  thing through one shared Mention node, regardless of surface form —
  Memory-MENTIONS->Mention<-MENTIONS-Memory (spec #29 story 2)
- ``depth=0`` (the default) is the status quo: the exact seed set, no
  bridging (story: explicit opt-in)
- the bridge respects B3 resolution semantics: type participates in the
  dedup key, so same-canonical-different-type nodes never bridge
- the walk is cycle-safe and entity-scoped: no duplicates, no dead
  loops, and another entity's memories never surface
- depth 2 chains through intermediate memories (a shared subject's
  other subjects) — chain provenance is asserted in #33

Deterministic labelled corpus + mock embeddings + rule-only path; the
engine fixture reuses the mention suite's corpus gazetteer (section 4).
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
ALICE_PY_ENTRY = HAPPY_PATH_CORPUS[3]  # Alice + Python
BOTH_ENTRY = HAPPY_PATH_CORPUS[4]  # Python + Google
GUGE_ENTRY = HAPPY_PATH_CORPUS[8]  # "用户在谷歌工作" → Google
UPPER_GOOGLE_ENTRY = HAPPY_PATH_CORPUS[9]  # "用户在 GOOGLE 工作" → Google



async def _seed_google_python_world(engine, entity_id: str) -> dict[str, str]:
    """Seed the world and return {label: memory_id}."""
    ids = {
        "google": await add_content(engine, entity_id, GOOGLE_ENTRY[0]),
        "guge": await add_content(engine, entity_id, GUGE_ENTRY[0]),
        "upper": await add_content(engine, entity_id, UPPER_GOOGLE_ENTRY[0]),
        "both": await add_content(engine, entity_id, BOTH_ENTRY[0]),
        "python": await add_content(engine, entity_id, PYTHON_ENTRY[0]),
        "alice_py": await add_content(engine, entity_id, ALICE_PY_ENTRY[0]),
    }
    return ids


async def test_depth0_is_the_t1_exact_set(engine, entity_id):
    """depth=0 (default): exactly the mentioning memories, no bridging."""
    ids = await _seed_google_python_world(engine, entity_id)

    results = await make_orchestrator(engine).search(
        "Google", entity_id=entity_id, search_mode=SearchMode.MEMORY,
        about="Google", depth=0,
    )
    assert {r.id for r in results.results} == {
        ids["google"], ids["guge"], ids["upper"], ids["both"],
    }


async def test_depth1_bridges_through_the_shared_mention(engine, entity_id):
    """depth=1: Python-only memories surface via the Google∩Python memory."""
    ids = await _seed_google_python_world(engine, entity_id)

    results = await make_orchestrator(engine).search(
        "Google", entity_id=entity_id, search_mode=SearchMode.MEMORY,
        about="Google", depth=1,
    )
    assert {r.id for r in results.results} == {
        ids["google"], ids["guge"], ids["upper"], ids["both"],
        ids["python"], ids["alice_py"],
    }


async def test_depth2_adds_nothing_and_never_duplicates(engine, entity_id):
    """The walk is bounded: depth 2 == depth 1 here, no duplicate ids."""
    ids = await _seed_google_python_world(engine, entity_id)

    depth1 = await make_orchestrator(engine).search(
        "Google", entity_id=entity_id, search_mode=SearchMode.MEMORY,
        about="Google", depth=1,
    )
    depth2 = await make_orchestrator(engine).search(
        "Google", entity_id=entity_id, search_mode=SearchMode.MEMORY,
        about="Google", depth=2,
    )
    ids1 = [r.id for r in depth1.results]
    ids2 = [r.id for r in depth2.results]
    assert sorted(ids2) == sorted(ids1)
    assert len(ids2) == len(set(ids2))
    assert ids["python"] in ids2 and ids["alice_py"] in ids2


async def test_bridging_is_entity_scoped(engine, entity_id):
    """Another entity's same-canonical memories never bridge in."""
    other_entity = f"{entity_id}_other"
    mine = await _seed_google_python_world(engine, entity_id)
    await _seed_google_python_world(engine, other_entity)

    results = await make_orchestrator(engine).search(
        "Google", entity_id=entity_id, search_mode=SearchMode.MEMORY,
        about="Google", depth=2,
    )
    ids = {r.id for r in results.results}
    assert ids == set(mine.values())


async def test_type_participates_in_the_bridge(engine, entity_id):
    """Same canonical form, different types never bridge (B3 semantics)."""
    from emerald.core.mentions import Mention

    mid_org = await add_content(engine, entity_id, GOOGLE_ENTRY[0])
    mid_tech = await add_content(engine, entity_id, PYTHON_ENTRY[0])
    # Give the Python memory a second mention: "Google" as a technology —
    # a different node from the organization "Google".
    await engine.graph.attach_mentions(
        mid_tech, entity_id, [Mention("Google", "Google", "technology", 0.9)],
    )

    results = await make_orchestrator(engine).search(
        "Google", entity_id=entity_id, search_mode=SearchMode.MEMORY,
        about="Google", depth=1,
    )
    ids = {r.id for r in results.results}
    # about=Google matches canonical form across types (T1 semantics), so
    # mid_tech is in the seed; but nothing NEW bridges via the tech node.
    assert mid_org in ids and mid_tech in ids
    assert len(ids) == 2
