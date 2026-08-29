"""Quality suite section 4f — UPDATES integration (ticket #26).

B3 T6 asserts, on the deterministic rule-only path:

- when a new memory UPDATES (replaces) an old one, the old memory keeps
  its MENTIONS edges — it is a historical node, not a forgotten one
  (acceptance criterion 1; spec #21 story 15)
- the replacing memory gets its own MENTIONS edges from its own
  extraction (criterion 2)
- MENTIONS edges are an independent reference category: the is_latest
  flip and replaced_by bookkeeping never touch them (criterion 3)
- update chains (A ← B ← C) keep every historical edge; a shared Mention
  node counts both the replaced memory's edge and the live one (criterion
  4, spec #21: 提及被正确承接)

The UPDATES relationship itself is triggered deterministically by the
rule classifier's structure-template route: "用户在 Google 工作" and
"用户在 Stripe 工作" share the template "用户在 * 工作" with different
fillers (spec #21 testing decision: 确定性测试路径).

Deterministic labelled corpus + mock embeddings + rule-only path,
same fixtures as sections 4 (#22) through 4e (#27).
"""

from __future__ import annotations

import pytest

from tests.quality.mentions.conftest import add_content
from tests.quality.mentions.corpus import HAPPY_PATH_CORPUS

pytestmark = [pytest.mark.quality]

# Corpus entries: (content, expected mentions).
GOOGLE_ENTRY = HAPPY_PATH_CORPUS[1]  # "用户在 Google 工作" → Google
STRIPE_ENTRY = HAPPY_PATH_CORPUS[2]  # "用户在 Stripe 工作" → Stripe
GUGE_ENTRY = HAPPY_PATH_CORPUS[8]  # "用户在谷歌工作" → Google (different surface)

# Structure-template twin of STRIPE_ENTRY with no corpus mention — the
# third leg of the update chain (rule classifier replaces "Apple" with
# the same template placeholder as "Stripe").
APPLE_ENTRY = ("用户在 Apple 工作", [])


async def test_updates_old_memory_keeps_historical_mentions(engine, entity_id):
    """The replaced memory keeps its MENTIONS edges; the replacer gets its own."""
    old_mid = await add_content(engine, entity_id, GOOGLE_ENTRY[0])
    new_mid = await add_content(engine, entity_id, STRIPE_ENTRY[0])

    # The rule path classified the pair as UPDATES: old is replaced...
    old = await engine.graph.get_memory(old_mid)
    assert old is not None
    assert old["is_latest"] is False
    assert old["replaced_by"] == new_mid

    # ...and the UPDATES edge exists (new → old).
    assert await engine.graph.get_relationships_to([old_mid]) == {old_mid: [new_mid]}

    # The old memory is history, but its MENTIONS edge survives (criterion 1).
    old_mentions = await engine.graph.get_memory_mentions(old_mid)
    assert [(m["canonical_form"], m["surface_form"]) for m in old_mentions] == [
        ("Google", "Google")
    ]
    assert old_mentions[0]["entity_id"] == entity_id

    # The new memory carries its own mention from its own extraction,
    # not an inherited one (criterion 2).
    new_mentions = await engine.graph.get_memory_mentions(new_mid)
    assert [(m["canonical_form"], m["surface_form"]) for m in new_mentions] == [
        ("Stripe", "Stripe")
    ]

    # Both Mention nodes are alive, one edge each.
    nodes = await engine.graph.get_entity_mentions(entity_id)
    assert sorted(n["canonical_form"] for n in nodes) == ["Google", "Stripe"]
    assert all(n["mention_count"] == 1 for n in nodes)


async def test_shared_mention_survives_update_with_historical_edge_counted(
    engine,
    entity_id,
):
    """A replaced memory's edge still counts on the shared Mention node."""
    old_mid = await add_content(engine, entity_id, GOOGLE_ENTRY[0])
    live_mid = await add_content(engine, entity_id, GUGE_ENTRY[0])

    # Both memories resolve to one shared Google node (count 2).
    nodes = await engine.graph.get_entity_mentions(entity_id)
    assert len(nodes) == 1
    assert nodes[0]["canonical_form"] == "Google"
    assert nodes[0]["mention_count"] == 2

    # The Stripe fact UPDATES the Google fact — the Google edge stays.
    # (It may also EXTENDS the 谷歌 memory incidentally; EXTENDS never
    # touches is_latest or MENTIONS edges either.)
    new_mid = await add_content(engine, entity_id, STRIPE_ENTRY[0])
    old = await engine.graph.get_memory(old_mid)
    assert old["is_latest"] is False and old["replaced_by"] == new_mid

    nodes = await engine.graph.get_entity_mentions(entity_id)
    by_canonical = {n["canonical_form"]: n for n in nodes}
    # The shared node keeps counting the replaced memory's historical edge.
    assert by_canonical["Google"]["mention_count"] == 2
    assert sorted(by_canonical["Google"]["aliases"]) == ["Google", "谷歌"]
    assert by_canonical["Stripe"]["mention_count"] == 1

    # The replaced memory still reads back its own edge to the shared node.
    old_mentions = await engine.graph.get_memory_mentions(old_mid)
    assert [(m["canonical_form"], m["surface_form"]) for m in old_mentions] == [
        ("Google", "Google")
    ]
    # The live memory still reads back its own edge too.
    live_mentions = await engine.graph.get_memory_mentions(live_mid)
    assert [(m["canonical_form"], m["surface_form"]) for m in live_mentions] == [("Google", "谷歌")]


async def test_update_chain_keeps_all_historical_mentions(engine, entity_id):
    """A ← B ← C: every replaced memory keeps its own historical edges."""
    mid_a = await add_content(engine, entity_id, GOOGLE_ENTRY[0])
    mid_b = await add_content(engine, entity_id, STRIPE_ENTRY[0])
    mid_c = await add_content(engine, entity_id, APPLE_ENTRY[0])

    a = await engine.graph.get_memory(mid_a)
    b = await engine.graph.get_memory(mid_b)
    c = await engine.graph.get_memory(mid_c)
    assert a["replaced_by"] == mid_b and b["replaced_by"] == mid_c
    assert c["is_latest"] is True

    # Each historical memory keeps exactly its own extraction's mentions.
    assert [
        (m["canonical_form"], m["surface_form"])
        for m in await engine.graph.get_memory_mentions(mid_a)
    ] == [("Google", "Google")]
    assert [
        (m["canonical_form"], m["surface_form"])
        for m in await engine.graph.get_memory_mentions(mid_b)
    ] == [("Stripe", "Stripe")]
    assert await engine.graph.get_memory_mentions(mid_c) == []

    # The chain's UPDATES edges point forward: B updates A, C updates B.
    assert await engine.graph.get_relationships_to([mid_a]) == {mid_a: [mid_b]}
    assert await engine.graph.get_relationships_to([mid_b]) == {mid_b: [mid_c]}

    # No mention node was pruned by the replacement bookkeeping.
    nodes = await engine.graph.get_entity_mentions(entity_id)
    assert sorted(n["canonical_form"] for n in nodes) == ["Google", "Stripe"]
    assert all(n["mention_count"] == 1 for n in nodes)


async def test_mentions_unaffected_by_is_latest_flip_and_replaced_by(
    engine,
    entity_id,
):
    """MENTIONS edges ignore is_latest flips and replaced_by bookkeeping."""
    mid = await add_content(engine, entity_id, GOOGLE_ENTRY[0])
    node_id = (await engine.graph.get_memory_mentions(mid))[0]["id"]

    await engine.graph.update_is_latest(mid, False, replaced_by="some_other_id")
    memory = await engine.graph.get_memory(mid)
    assert memory["is_latest"] is False
    assert memory["replaced_by"] == "some_other_id"

    # The edge and the node are untouched by the bookkeeping...
    mentions = await engine.graph.get_memory_mentions(mid)
    assert [(m["id"], m["canonical_form"]) for m in mentions] == [(node_id, "Google")]
    nodes = await engine.graph.get_entity_mentions(entity_id)
    assert [n["id"] for n in nodes] == [node_id]
    assert nodes[0]["mention_count"] == 1

    # ...and a flip back to latest changes nothing either.
    await engine.graph.update_is_latest(mid, True)
    mentions = await engine.graph.get_memory_mentions(mid)
    assert [(m["id"], m["canonical_form"]) for m in mentions] == [(node_id, "Google")]
    assert [n["id"] for n in await engine.graph.get_entity_mentions(entity_id)] == [node_id]
