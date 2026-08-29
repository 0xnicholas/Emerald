"""Quality suite section 4b — mention resolution + cross-memory dedup (#23).

B3 T2 asserts, on the deterministic rule-only path:

- two memories mentioning the same real-world thing with different surface
  forms ("Google" / "谷歌") resolve to a **single** Mention node inside the
  entity's context pool — the dedup key is (entity_id, canonical_form, type)
  (spec #21 user stories 8, 13)
- the resolved node accumulates every seen surface form as an alias (story 12)
- each contributing memory carries its own MENTIONS edge to the shared node
  (story 9) — N memories mentioning the same thing mean 1 node + N edges,
  with mention_count == N (no node duplication)
- re-attaching the same memory's mentions is idempotent: no duplicate node,
  no duplicate edge, no count inflation
- the dedup key is entity-scoped: the same canonical form mentioned in two
  entities stays two separate nodes (story 7 — full leakage matrix in #25)

Deterministic labelled corpus + mock embeddings + rule-only path, same
fixtures as section 4 (#22).
"""

from __future__ import annotations

import pytest

from emerald.core.mentions import Mention
from tests.quality.mentions.conftest import add_content
from tests.quality.mentions.corpus import HAPPY_PATH_CORPUS

pytestmark = [pytest.mark.quality]

# Corpus entries: (content, expected mentions).
GOOGLE_ENTRY = HAPPY_PATH_CORPUS[1]  # "用户在 Google 工作"
GUGE_ENTRY = HAPPY_PATH_CORPUS[8]  # "用户在谷歌工作"
UPPER_GOOGLE_ENTRY = HAPPY_PATH_CORPUS[9]  # "用户在 GOOGLE 工作"




async def test_different_surface_forms_resolve_to_one_node(engine, entity_id):
    """'Google' and '谷歌' in two memories → one shared Mention node."""
    google_mid = await add_content(engine, entity_id, GOOGLE_ENTRY[0])
    guge_mid = await add_content(engine, entity_id, GUGE_ENTRY[0])

    google_mentions = await engine.graph.get_memory_mentions(google_mid)
    guge_mentions = await engine.graph.get_memory_mentions(guge_mid)
    assert len(google_mentions) == 1
    assert len(guge_mentions) == 1
    assert google_mentions[0]["id"] == guge_mentions[0]["id"]
    assert google_mentions[0]["canonical_form"] == "Google"
    assert guge_mentions[0]["canonical_form"] == "Google"

    # The entity's pool holds exactly one mention node.
    pool = engine.graph._mentions.get(entity_id, [])
    assert len(pool) == 1
    assert pool[0]["id"] == google_mentions[0]["id"]


async def test_node_accumulates_all_seen_surface_forms_as_aliases(
    engine,
    entity_id,
):
    """The resolved node aliases accumulate every surface form seen."""
    await add_content(engine, entity_id, GOOGLE_ENTRY[0])
    await add_content(engine, entity_id, GUGE_ENTRY[0])

    pool = engine.graph._mentions.get(entity_id, [])
    assert len(pool) == 1
    node = pool[0]
    assert node["canonical_form"] == "Google"
    assert node["type"] == "organization"
    assert sorted(node["aliases"]) == ["Google", "谷歌"]
    assert node["mention_count"] == 2


async def test_each_memory_keeps_its_own_edge_to_the_shared_node(
    engine,
    entity_id,
):
    """Both memories carry a MENTIONS edge to the same node, one each."""
    google_mid = await add_content(engine, entity_id, GOOGLE_ENTRY[0])
    guge_mid = await add_content(engine, entity_id, GUGE_ENTRY[0])

    google_memory = await engine.graph.get_memory(google_mid)
    guge_memory = await engine.graph.get_memory(guge_mid)
    google_edges = google_memory.get("mentions", [])
    guge_edges = guge_memory.get("mentions", [])
    assert len(google_edges) == 1
    assert len(guge_edges) == 1
    assert google_edges[0]["mention_id"] == guge_edges[0]["mention_id"]
    assert google_edges[0]["surface_form"] == "Google"
    assert guge_edges[0]["surface_form"] == "谷歌"


async def test_repeated_mentions_one_node_n_edges(engine, entity_id):
    """N memories mentioning the same thing → 1 node, N edges, count N."""
    # Three distinct contents (engine dedupes identical content) that all
    # mention the same real-world thing with different surface forms.
    memory_ids = [
        await add_content(engine, entity_id, entry[0])
        for entry in (GOOGLE_ENTRY, GUGE_ENTRY, UPPER_GOOGLE_ENTRY)
    ]

    pool = engine.graph._mentions.get(entity_id, [])
    assert len(pool) == 1
    node = pool[0]
    assert node["canonical_form"] == "Google"
    assert node["mention_count"] == 3
    assert sorted(node["aliases"]) == ["GOOGLE", "Google", "谷歌"]

    # Every memory reads back its own edge to the shared node.
    for mid in memory_ids:
        mentions = await engine.graph.get_memory_mentions(mid)
        assert [m["id"] for m in mentions] == [node["id"]]


async def test_attach_same_memory_again_is_idempotent(engine, entity_id):
    """Re-attaching the same memory's mentions changes nothing."""
    mid = await add_content(engine, entity_id, GOOGLE_ENTRY[0])
    mentions = await engine.graph.get_memory_mentions(mid)
    assert len(mentions) == 1

    reattached = await engine.graph.attach_mentions(
        mid,
        entity_id,
        [Mention("Google", "Google", "organization", 0.9)],
    )
    assert reattached == 0
    pool = engine.graph._mentions.get(entity_id, [])
    assert len(pool) == 1
    assert pool[0]["mention_count"] == 1
    assert len(await engine.graph.get_memory_mentions(mid)) == 1


async def test_same_canonical_in_two_entities_stays_two_nodes(
    engine,
    entity_id,
):
    """The dedup key is entity-scoped — no cross-entity node sharing."""
    other_entity = f"{entity_id}_other"
    mid_a = await add_content(engine, entity_id, GOOGLE_ENTRY[0])
    mid_b = await add_content(engine, other_entity, GOOGLE_ENTRY[0])

    node_a = (await engine.graph.get_memory_mentions(mid_a))[0]
    node_b = (await engine.graph.get_memory_mentions(mid_b))[0]
    assert node_a["id"] != node_b["id"]
    assert node_a["entity_id"] == entity_id
    assert node_b["entity_id"] == other_entity
    assert {node_a["id"]} == {n["id"] for n in engine.graph._mentions[entity_id]}
    assert {node_b["id"]} == {n["id"] for n in engine.graph._mentions[other_entity]}


async def test_same_canonical_different_type_stays_two_nodes(
    engine,
    entity_id,
):
    """The dedup key includes type — same canonical, different type splits.

    "Apple" the organization and "Apple" the technology are distinct
    mentions (spec #21: no cross-type merging in B3).
    """
    mid = await add_content(engine, entity_id, HAPPY_PATH_CORPUS[0][0])
    await engine.graph.attach_mentions(
        mid,
        entity_id,
        [
            Mention("Apple", "Apple", "organization", 0.9),
            Mention("Apple", "Apple", "technology", 0.9),
        ],
    )
    pool = engine.graph._mentions.get(entity_id, [])
    apples = [n for n in pool if n["canonical_form"] == "Apple"]
    assert len(apples) == 2
    assert {n["type"] for n in apples} == {"organization", "technology"}
