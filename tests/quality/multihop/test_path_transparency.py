"""Quality suite section 5d — path transparency & ranking (B4, ticket #33).

B4 T4 asserts, on the deterministic rule-only path:

- seeds (vector/about hits) carry depth 0 and an empty path — the
  status quo is untouched (spec #29 story 5, #33 depth 默认 0)
- every multihop result carries ``depth`` (hop count) and ``path``
  (the full walk from the seed: memory nodes, shared Mention nodes,
  relationship edges) — spec #29 story 4, #33
- ranking: multihop results are annotated with their hop depth and,
  on the deterministic corpus, seeds strictly precede them (spec #33:
  种子向量命中在前，多跳结果标注来源跳数)
- historical nodes surfaced along UPDATES chains keep their provenance
  path and are marked is_latest=False (spec #29 story 7)

Deterministic labelled corpus + mock embeddings + rule-only path; the
engine fixture reuses the mention suite's corpus gazetteer (section 4).
Relationship worlds use pairwise-disjoint sentences so the rule-only
RelationshipEngine creates no edges of its own (section 5c pattern).
"""

from __future__ import annotations

import pytest

from emerald.core.mentions import Mention
from emerald.core.search import SearchMode, SearchOrchestrator
from tests.quality.mentions.conftest import add_content
from tests.quality.mentions.corpus import HAPPY_PATH_CORPUS

pytestmark = [pytest.mark.quality]

PYTHON_ENTRY = HAPPY_PATH_CORPUS[0]  # "用户用 Python 写数据管线"
GOOGLE_ENTRY = HAPPY_PATH_CORPUS[1]  # "用户在 Google 工作"
GUGE_ENTRY = HAPPY_PATH_CORPUS[8]  # "用户在谷歌工作"
BOTH_ENTRY = HAPPY_PATH_CORPUS[4]  # Python + Google


def _orchestrator(engine) -> SearchOrchestrator:
    return SearchOrchestrator(
        graph=engine.graph,
        vector=engine.vector,
        fast_lane_store=engine.fast_lane_store,
        embedder=engine.embedder,
    )


async def test_seeds_are_depth0_with_empty_path(engine, entity_id):
    """depth=0 (default): every result is a seed — depth 0, no path."""
    ids = {
        "google": await add_content(engine, entity_id, GOOGLE_ENTRY[0]),
        "guge": await add_content(engine, entity_id, GUGE_ENTRY[0]),
        "both": await add_content(engine, entity_id, BOTH_ENTRY[0]),
    }

    results = await _orchestrator(engine).search(
        "Google", entity_id=entity_id, search_mode=SearchMode.MEMORY,
        about="Google", depth=0,
    )
    assert {r.id for r in results.results} == set(ids.values())
    for r in results.results:
        assert r.depth == 0
        assert r.path == []


async def test_mention_bridge_carries_full_path(engine, entity_id):
    """A bridged memory's path is seed → shared Mention node → memory."""
    ids = {
        "google": await add_content(engine, entity_id, GOOGLE_ENTRY[0]),
        "guge": await add_content(engine, entity_id, GUGE_ENTRY[0]),
        "both": await add_content(engine, entity_id, BOTH_ENTRY[0]),
        "python": await add_content(engine, entity_id, PYTHON_ENTRY[0]),
    }

    results = await _orchestrator(engine).search(
        "Google", entity_id=entity_id, search_mode=SearchMode.MEMORY,
        about="Google", depth=1,
    )
    by_id = {r.id: r for r in results.results}
    for seed_id in (ids["google"], ids["guge"], ids["both"]):
        assert by_id[seed_id].depth == 0
        assert by_id[seed_id].path == []

    bridged = by_id[ids["python"]]
    assert bridged.depth == 1
    assert [s.kind for s in bridged.path] == ["memory", "mention", "memory"]
    assert bridged.path[0].id == ids["both"]
    assert bridged.path[-1].id == ids["python"]
    # The middle step is the shared Python Mention node of the
    # Google∩Python memory.
    mention_node = next(
        m for m in await engine.graph.get_memory_mentions(ids["both"])
        if m["canonical_form"] == "Python"
    )
    assert bridged.path[1].kind == "mention"
    assert bridged.path[1].id == mention_node["id"]


async def test_derives_chain_carries_relationship_path(engine, entity_id):
    """D2's path is A2 ←(DF) D1 ←(DF) D2; A's path is A2 →(UPDATES) A."""
    a_content = "猫在房顶上睡觉"
    a2_content = "冰箱里有牛奶"
    d1_content = "窗外下着大雨"
    d2_content = "桌上放着铅笔"
    ids = {
        "a": await add_content(engine, entity_id, a_content),
        "a2": await add_content(engine, entity_id, a2_content),
        "d1": await add_content(engine, entity_id, d1_content),
        "d2": await add_content(engine, entity_id, d2_content),
    }
    for label in ("a", "a2"):
        await engine.graph.attach_mentions(
            ids[label], entity_id, [Mention("Foo", "Foo", "concept", 0.9)],
        )
    await engine.graph.create_update_relation(ids["a2"], ids["a"])
    await engine.graph.create_relationship(ids["d1"], ids["a2"], "DERIVES_FROM")
    await engine.graph.create_relationship(ids["d2"], ids["d1"], "DERIVES_FROM")

    results = await _orchestrator(engine).search(
        "Foo", entity_id=entity_id, search_mode=SearchMode.MEMORY,
        about="Foo", depth=2,
    )
    by_id = {r.id: r for r in results.results}

    assert by_id[ids["a2"]].depth == 0 and by_id[ids["a2"]].path == []
    assert by_id[ids["d1"]].depth == 1
    assert [
        (s.kind, s.id) for s in by_id[ids["d1"]].path
    ] == [("memory", ids["a2"]), ("DERIVES_FROM", ids["d1"])]
    assert by_id[ids["d2"]].depth == 2
    assert [
        (s.kind, s.id) for s in by_id[ids["d2"]].path
    ] == [
        ("memory", ids["a2"]),
        ("DERIVES_FROM", ids["d1"]),
        ("DERIVES_FROM", ids["d2"]),
    ]
    # Historical node: surfaced along UPDATES with its provenance.
    assert by_id[ids["a"]].depth == 1
    assert by_id[ids["a"]].is_latest is False
    assert [
        (s.kind, s.id) for s in by_id[ids["a"]].path
    ] == [("memory", ids["a2"]), ("UPDATES", ids["a"])]


async def test_ranking_seeds_first_multihop_annotated(engine, entity_id):
    """Seeds occupy the head; every later result carries a hop depth.

    On the deterministic corpus the ranking is strict: every multihop
    result scores trust×0.85^depth, below any seed's trust score, so
    seeds precede multihop results and depth-1 precedes depth-2.
    """
    ids = {
        "google": await add_content(engine, entity_id, GOOGLE_ENTRY[0]),
        "guge": await add_content(engine, entity_id, GUGE_ENTRY[0]),
        "both": await add_content(engine, entity_id, BOTH_ENTRY[0]),
        "python": await add_content(engine, entity_id, PYTHON_ENTRY[0]),
    }

    results = await _orchestrator(engine).search(
        "Google", entity_id=entity_id, search_mode=SearchMode.MEMORY,
        about="Google", depth=1,
    )
    depths = [r.depth for r in results.results]
    # Three seeds first (all depth 0), then the bridged memory at depth 1.
    assert depths == [0, 0, 0, 1]
    # Seeds rank strictly above the multihop result: the bridged memory
    # is scored trust×0.85^depth, below any seed's trust score.
    assert results.results[-1].id == ids["python"]
    assert results.results[-1].score < min(
        r.score for r in results.results if r.depth == 0
    )
