"""Quality suite section 5e — cycle safety (B4, ticket #34).

B4 asserts, on the deterministic rule-only path, that multihop walks
are loop-safe (spec #29 story 10): mutually-referencing memories —
through shared Mention nodes, through relationship edges, or through
both at once — never dead-loop, never duplicate a result, and every
result carries its shallowest depth.

Deterministic labelled corpus + mock embeddings + rule-only path; the
engine fixture reuses the mention suite's corpus gazetteer (section 4).
Cycle edges are created explicitly so the cycle, not the inference, is
under test.
"""

from __future__ import annotations

import pytest

from emerald.core.mentions import Mention
from emerald.core.search import SearchMode
from tests.quality.mentions.conftest import add_content
from tests.quality.mentions.corpus import HAPPY_PATH_CORPUS
from tests.quality.multihop.conftest import make_orchestrator

pytestmark = [pytest.mark.quality]

GOOGLE_ENTRY = HAPPY_PATH_CORPUS[1]  # "用户在 Google 工作"
GUGE_ENTRY = HAPPY_PATH_CORPUS[8]  # "用户在谷歌工作"


async def test_mutual_mention_cycle_is_bounded(engine, entity_id):
    """A↔B bridging through one shared node, seeded from A only.

    B bridges back to A at the next level; the visited set stops the
    cycle — each memory appears exactly once, B at depth 1.
    """
    mid_a = await add_content(engine, entity_id, GOOGLE_ENTRY[0])
    mid_b = await add_content(engine, entity_id, GUGE_ENTRY[0])
    # A alone mentions Foo — the single-seed entry point. Both mention
    # canonical Google (the gazetteer resolves 谷歌 → Google), so the
    # Google node is a mutual bridge.
    await engine.graph.attach_mentions(
        mid_a, entity_id, [Mention("Foo", "Foo", "concept", 0.9)],
    )

    results = await make_orchestrator(engine).search(
        "Foo", entity_id=entity_id, search_mode=SearchMode.MEMORY,
        about="Foo", depth=4,
    )
    ids = [r.id for r in results.results]
    assert set(ids) == {mid_a, mid_b}
    # No duplicates, and the bridged memory carries its shallowest depth.
    assert len(ids) == len(set(ids))
    by_id = {r.id: r for r in results.results}
    assert by_id[mid_a].depth == 0
    assert by_id[mid_b].depth == 1


async def test_mutual_relationship_cycle_is_bounded(engine, entity_id):
    """A -EXTENDS-> B and B -EXTENDS-> A: each surface once, no dead loop."""
    a_content = "猫在房顶上睡觉"
    b_content = "冰箱里有牛奶"
    mid_a = await add_content(engine, entity_id, a_content)
    mid_b = await add_content(engine, entity_id, b_content)
    await engine.graph.attach_mentions(
        mid_a, entity_id, [Mention("Foo", "Foo", "concept", 0.9)],
    )
    await engine.graph.create_relationship(mid_a, mid_b, "EXTENDS")
    await engine.graph.create_relationship(mid_b, mid_a, "EXTENDS")

    results = await make_orchestrator(engine).search(
        "Foo", entity_id=entity_id, search_mode=SearchMode.MEMORY,
        about="Foo", depth=4,
    )
    ids = [r.id for r in results.results]
    assert set(ids) == {mid_a, mid_b}
    assert len(ids) == len(set(ids))
    by_id = {r.id: r for r in results.results}
    assert by_id[mid_a].depth == 0
    assert by_id[mid_b].depth == 1
    # The seed is never re-added by the cycle (visited-set safety).
    assert ids[0] == mid_a


async def test_mixed_mention_and_relationship_cycle(engine, entity_id):
    """A cycle that interleaves a mention bridge and an EXTENDS edge."""
    mid_a = await add_content(engine, entity_id, GOOGLE_ENTRY[0])
    mid_b = await add_content(engine, entity_id, GUGE_ENTRY[0])
    await engine.graph.attach_mentions(
        mid_a, entity_id, [Mention("Foo", "Foo", "concept", 0.9)],
    )
    await engine.graph.create_relationship(mid_b, mid_a, "EXTENDS")

    results = await make_orchestrator(engine).search(
        "Foo", entity_id=entity_id, search_mode=SearchMode.MEMORY,
        about="Foo", depth=4,
    )
    ids = [r.id for r in results.results]
    # B is reachable both via the shared mention and via the EXTENDS edge
    # (inbound) — it must appear exactly once, at depth 1.
    assert set(ids) == {mid_a, mid_b}
    assert len(ids) == len(set(ids))
    by_id = {r.id: r for r in results.results}
    assert by_id[mid_b].depth == 1


async def test_cycle_with_two_seeds_still_deduplicates(engine, entity_id):
    """Expanding from both cycle members traverses and dedups (B4 #34).

    A and B are mutual EXTENDS cycle members AND both are about seeds;
    C extends A. The walk from both seeds reaches C once at depth 1 and
    never re-adds either cycle member.
    """
    mid_a = await add_content(engine, entity_id, GOOGLE_ENTRY[0])
    mid_b = await add_content(engine, entity_id, GUGE_ENTRY[0])
    mid_c = await add_content(engine, entity_id, "桌上放着铅笔")
    await engine.graph.create_relationship(mid_a, mid_b, "EXTENDS")
    await engine.graph.create_relationship(mid_b, mid_a, "EXTENDS")
    await engine.graph.create_relationship(mid_c, mid_a, "EXTENDS")

    results = await make_orchestrator(engine).search(
        "Google", entity_id=entity_id, search_mode=SearchMode.MEMORY,
        about="Google", depth=4,
    )
    ids = [r.id for r in results.results]
    assert set(ids) == {mid_a, mid_b, mid_c}
    assert len(ids) == len(set(ids))
    by_id = {r.id: r for r in results.results}
    # Both cycle members are seeds; the cycle never re-adds them.
    assert by_id[mid_a].depth == 0
    assert by_id[mid_b].depth == 0
    assert by_id[mid_c].depth == 1
