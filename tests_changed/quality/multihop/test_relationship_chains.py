"""Quality suite section 5c — relationship chains (B4, ticket #32).

B4 T3 asserts, on the deterministic rule-only path:

- querying a source fact surfaces the derived fact (reverse
  DERIVES_FROM) and chains: D2 derives from D1 derives from A2 → D2
  arrives at depth 2 (spec #29 story 3)
- EXTENDS walks in both directions; both facts stay current
- historical nodes (is_latest=False) surface ONLY along UPDATES edges,
  are marked ``is_latest=False`` in the result, and are terminals —
  never walked through (spec #29 story 7)
- the walk is entity-scoped: another entity's derived facts never
  surface, even when an edge points across entities
- depth is clamped to 4 (spec #29 上限 4): a 6-edge chain stops at the
  4th hop

Deterministic labelled corpus + mock embeddings + rule-only path; the
engine fixture reuses the mention suite's corpus gazetteer (section 4).
Contents are deliberately pairwise-disjoint sentences: the rule-only
RelationshipEngine classifies pairs with no bigram/subject overlap as
NONE, so the graph's only edges are the ones the test creates
explicitly — the walk, not the inference, is under test.
"""

from __future__ import annotations

import pytest

from emerald.core.mentions import Mention
from emerald.core.multihop import MultihopEngine
from emerald.core.search import SearchMode
from tests.quality.mentions.conftest import add_content
from tests.quality.multihop.conftest import make_orchestrator

pytestmark = [pytest.mark.quality]

# The chain world — pairwise-disjoint sentences, see module docstring.
A_CONTENT = "猫在房顶上睡觉"      # historical fact (superseded by A2)
A2_CONTENT = "冰箱里有牛奶"       # current fact, seeds via Foo
D1_CONTENT = "窗外下着大雨"       # derives from A2
D2_CONTENT = "桌上放着铅笔"       # derives from D1
X_CONTENT = "河里游着金鱼"        # extends A2
E_CONTENT = "树下堆着落叶"        # unrelated, also mentions Foo (2nd seed)
C_OTHER_CONTENT = "天上飘着白云"  # another entity, derives from D1



async def _seed_chain_world(engine, entity_id: str) -> dict[str, str]:
    """Seed the chain world and return {label: memory_id}.

    Graph (entity e): A2 -UPDATES-> A; D1 -DERIVES_FROM-> A2;
    D2 -DERIVES_FROM-> D1; X -EXTENDS-> A2; E isolated; A, A2, E mention
    Foo. Entity other: C -DERIVES_FROM-> D1 (cross-entity edge).
    """
    ids = {
        "a": await add_content(engine, entity_id, A_CONTENT),
        "a2": await add_content(engine, entity_id, A2_CONTENT),
        "d1": await add_content(engine, entity_id, D1_CONTENT),
        "d2": await add_content(engine, entity_id, D2_CONTENT),
        "x": await add_content(engine, entity_id, X_CONTENT),
        "e": await add_content(engine, entity_id, E_CONTENT),
    }
    for label in ("a", "a2", "e"):
        await engine.graph.attach_mentions(
            ids[label], entity_id, [Mention("Foo", "Foo", "concept", 0.9)],
        )
    # A2 supersedes A: A becomes historical (is_latest=False).
    await engine.graph.create_update_relation(ids["a2"], ids["a"])
    await engine.graph.create_relationship(ids["d1"], ids["a2"], "DERIVES_FROM")
    await engine.graph.create_relationship(ids["d2"], ids["d1"], "DERIVES_FROM")
    await engine.graph.create_relationship(ids["x"], ids["a2"], "EXTENDS")

    other_entity = f"{entity_id}_other"
    c_id = await add_content(engine, other_entity, C_OTHER_CONTENT)
    await engine.graph.create_relationship(c_id, ids["d1"], "DERIVES_FROM")
    ids["c_other"] = c_id
    return ids


async def test_depth0_returns_only_the_about_seeds(engine, entity_id):
    """depth=0 (default): exactly the current facts mentioning Foo."""
    ids = await _seed_chain_world(engine, entity_id)

    results = await make_orchestrator(engine).search(
        "Foo", entity_id=entity_id, search_mode=SearchMode.MEMORY,
        about="Foo", depth=0,
    )
    # A2 and E mention Foo and are latest; A is historical and thus not
    # an about seed — no traversal means nothing else surfaces.
    assert {r.id for r in results.results} == {ids["a2"], ids["e"]}


async def test_depth1_surfaces_derived_and_history(engine, entity_id):
    """Depth 1: reverse DERIVES_FROM + EXTENDS + UPDATES history, marked."""
    ids = await _seed_chain_world(engine, entity_id)

    results = await make_orchestrator(engine).search(
        "Foo", entity_id=entity_id, search_mode=SearchMode.MEMORY,
        about="Foo", depth=1,
    )
    by_id = {r.id: r for r in results.results}
    assert set(by_id) == {ids["a2"], ids["e"], ids["a"], ids["d1"], ids["x"]}
    # The superseded fact surfaced along the UPDATES chain, marked.
    assert by_id[ids["a"]].is_latest is False
    assert by_id[ids["d1"]].is_latest is True
    assert by_id[ids["x"]].is_latest is True
    # Two hops away: not yet.
    assert ids["d2"] not in by_id


async def test_derives_chain_depth2_exact(engine, entity_id):
    """D2 derives from D1 derives from A2: depth 2 reaches exactly D2."""
    ids = await _seed_chain_world(engine, entity_id)

    depth1 = await make_orchestrator(engine).search(
        "Foo", entity_id=entity_id, search_mode=SearchMode.MEMORY,
        about="Foo", depth=1,
    )
    depth2 = await make_orchestrator(engine).search(
        "Foo", entity_id=entity_id, search_mode=SearchMode.MEMORY,
        about="Foo", depth=2,
    )
    ids1 = {r.id for r in depth1.results}
    ids2 = {r.id for r in depth2.results}
    assert ids["d2"] not in ids1
    assert ids["d2"] in ids2
    assert ids2 == {
        ids["a2"], ids["e"], ids["a"], ids["d1"], ids["x"], ids["d2"],
    }
    # No duplicates: every memory appears exactly once.
    assert len(ids2) == len(depth2.results)


async def test_cross_entity_edge_never_surfaces(engine, entity_id):
    """C (other entity) derives from D1 — the walk never leaves the pool."""
    ids = await _seed_chain_world(engine, entity_id)

    results = await make_orchestrator(engine).search(
        "Foo", entity_id=entity_id, search_mode=SearchMode.MEMORY,
        about="Foo", depth=5,
    )
    surfaced = {r.id for r in results.results}
    assert ids["c_other"] not in surfaced
    assert ids["d1"] in surfaced and ids["d2"] in surfaced


async def test_engine_walk_exposes_depths_and_paths(engine, entity_id):
    """The engine's Hop payload carries depth, path and historical flag."""
    ids = await _seed_chain_world(engine, entity_id)

    hops = await MultihopEngine(graph=engine.graph).expand(
        [ids["a2"]], entity_id, depth=2,
    )
    # e shares the Foo mention node with a2, so the mention bridge
    # surfaces it alongside the relationship hops.
    assert set(hops) == {ids["a"], ids["d1"], ids["d2"], ids["x"], ids["e"]}
    assert hops[ids["a"]].depth == 1 and hops[ids["a"]].historical is True
    assert hops[ids["a"]].path == [("memory", ids["a2"]), ("UPDATES", ids["a"])]
    assert hops[ids["d1"]].depth == 1 and hops[ids["d1"]].historical is False
    assert hops[ids["d2"]].depth == 2
    assert hops[ids["d2"]].path == [
        ("memory", ids["a2"]),
        ("DERIVES_FROM", ids["d1"]),
        ("DERIVES_FROM", ids["d2"]),
    ]


async def test_depth_cap_at_four(engine, entity_id):
    """A 6-edge DERIVES chain is cut at depth 4 (spec #29 上限 4)."""
    chain = [
        "燕子飞回南方", "蝴蝶落在花上", "蜜蜂采着花蜜",
        "蚂蚁搬着米粒", "蝉鸣响彻夏日", "蜻蜓掠过水面",
    ]
    ids = [await add_content(engine, entity_id, content) for content in chain]
    await engine.graph.attach_mentions(
        ids[0], entity_id, [Mention("Foo2", "Foo2", "concept", 0.9)],
    )
    for derived, source in zip(ids[1:], ids, strict=False):
        await engine.graph.create_relationship(derived, source, "DERIVES_FROM")

    results = await make_orchestrator(engine).search(
        "Foo2", entity_id=entity_id, search_mode=SearchMode.MEMORY,
        about="Foo2", depth=5,  # clamped to 4
    )
    surfaced = {r.id for r in results.results}
    assert ids[0] in surfaced
    assert {ids[1], ids[2], ids[3], ids[4]} <= surfaced
    assert ids[5] not in surfaced
