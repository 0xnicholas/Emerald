"""Quality suite section 4e — forgetting integration (ticket #27).

B3 T5 asserts, on the deterministic rule-only path:

- forgetting a memory removes its MENTIONS edges (acceptance criterion 1)
- a Mention node left with zero MENTIONS edges is pruned from the entity's
  pool — the graph never accumulates dead mention nodes (criterion 2)
- a Mention node still referenced by another memory survives, with
  mention_count decremented to the number of remaining live edges
  (criterion 3)
- the pruning rides **every** forgetting strategy (time expiry, noise
  filtering, episodic decay): mark_expired is the shared seam those
  strategies funnel through (spec #21: "扩展现有遗忘路径")
- the UPDATES replacement path is untouched — a replaced memory keeps its
  historical MENTIONS edges (#26, regression guard)

Deterministic labelled corpus + mock embeddings + rule-only path,
same fixtures as sections 4 (#22) and 4b (#23).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from emerald.core.forget import ForgetEngine
from tests.quality.conftest import backdate
from tests.quality.mentions.conftest import add_content
from tests.quality.mentions.corpus import HAPPY_PATH_CORPUS

pytestmark = [pytest.mark.quality]

# Corpus entries: (content, expected mentions).
GOOGLE_ENTRY = HAPPY_PATH_CORPUS[1]  # "用户在 Google 工作" → Google
GUGE_ENTRY = HAPPY_PATH_CORPUS[8]  # "用户在谷歌工作" → Google (different surface)
PYTHON_ENTRY = HAPPY_PATH_CORPUS[0]  # "用户用 Python 写数据管线" → Python
BOTH_ENTRY = HAPPY_PATH_CORPUS[4]  # Python + Google in one memory


async def test_forgetting_removes_memory_mentions_edges(engine, entity_id):
    """Forgetting a memory removes exactly its MENTIONS edges (criterion 1)."""
    past = datetime.now(UTC) - timedelta(hours=1)
    result = await engine.add(BOTH_ENTRY[0], entity_id=entity_id, valid_until=past)
    forgotten_mid = result.memory_ids[0]
    survivor_mid = await add_content(engine, entity_id, GUGE_ENTRY[0])

    # Before forgetting: the doomed memory carries 2 edges, the survivor 1.
    assert len(await engine.graph.get_memory_mentions(forgotten_mid)) == 2
    assert len(await engine.graph.get_memory_mentions(survivor_mid)) == 1

    count = await ForgetEngine(graph=engine.graph).forget_expired(entity_id)
    assert count == 1

    forgotten = await engine.graph.get_memory(forgotten_mid)
    assert forgotten is not None and forgotten["is_latest"] is False
    # Its MENTIONS edges are gone...
    assert await engine.graph.get_memory_mentions(forgotten_mid) == []
    # ...and the surviving memory's edge is untouched.
    survivor_mentions = await engine.graph.get_memory_mentions(survivor_mid)
    assert [m["canonical_form"] for m in survivor_mentions] == ["Google"]


async def test_forgetting_last_reference_prunes_orphan_node(engine, entity_id):
    """Zero remaining MENTIONS edges prunes the Mention node (criterion 2)."""
    past = datetime.now(UTC) - timedelta(hours=1)
    await engine.add(GOOGLE_ENTRY[0], entity_id=entity_id, valid_until=past)
    python_mid = await add_content(engine, entity_id, PYTHON_ENTRY[0])

    pool = engine.graph._mentions.get(entity_id, [])
    assert len(pool) == 2  # Google + Python, one node each

    await ForgetEngine(graph=engine.graph).forget_expired(entity_id)

    # The Google node (referenced only by the forgotten memory) is pruned;
    # the Python node (referenced by a live memory) survives.
    remaining = await engine.graph.get_entity_mentions(entity_id)
    assert [n["canonical_form"] for n in remaining] == ["Python"]
    assert [n["id"] for n in remaining] == [
        (await engine.graph.get_memory_mentions(python_mid))[0]["id"]
    ]


async def test_shared_mention_survives_with_decremented_count(engine, entity_id):
    """A still-referenced Mention node survives, count = live edges (criterion 3)."""
    past = datetime.now(UTC) - timedelta(hours=1)
    await engine.add(GOOGLE_ENTRY[0], entity_id=entity_id, valid_until=past)
    survivor_mid = await add_content(engine, entity_id, GUGE_ENTRY[0])

    # Both memories resolve to one shared Google node with count 2.
    nodes = await engine.graph.get_entity_mentions(entity_id)
    assert len(nodes) == 1
    shared = nodes[0]
    assert shared["canonical_form"] == "Google"
    assert shared["mention_count"] == 2

    await ForgetEngine(graph=engine.graph).forget_expired(entity_id)

    # The node survives with the one remaining live edge counted; the
    # historical aliases are kept (surface forms ever seen).
    nodes = await engine.graph.get_entity_mentions(entity_id)
    assert len(nodes) == 1
    node = nodes[0]
    assert node["id"] == shared["id"]
    assert node["mention_count"] == 1
    assert sorted(node["aliases"]) == ["Google", "谷歌"]

    # The surviving memory still reads back its own edge to the node.
    survivor_mentions = await engine.graph.get_memory_mentions(survivor_mid)
    assert [m["id"] for m in survivor_mentions] == [shared["id"]]
    assert survivor_mentions[0]["surface_form"] == "谷歌"


async def _ingest_and_forget(engine, entity_id: str, strategy: str) -> str:
    """Ingest one memory with a mention and forget it via ``strategy``."""
    if strategy == "time_expiry":
        past = datetime.now(UTC) - timedelta(hours=1)
        result = await engine.add(GOOGLE_ENTRY[0], entity_id=entity_id, valid_until=past)
        mid = result.memory_ids[0]
        count = await ForgetEngine(graph=engine.graph).forget_expired(entity_id)
        assert count == 1
    elif strategy == "noise":
        result = await engine.add(
            GOOGLE_ENTRY[0],
            entity_id=entity_id,
            confidence=0.2,
        )
        mid = result.memory_ids[0]
        await backdate(engine.graph, entity_id, mid, days=8)
        count = await ForgetEngine(graph=engine.graph).forget_noise(entity_id)
        assert count == 1
    elif strategy == "episodic":
        result = await engine.add(
            GOOGLE_ENTRY[0],
            entity_id=entity_id,
            memory_type="episodic",
        )
        mid = result.memory_ids[0]
        await backdate(engine.graph, entity_id, mid, days=91)
        count = await ForgetEngine(graph=engine.graph).decay_episodic()
        assert count == 1
    else:  # pragma: no cover — parametrization is closed
        raise ValueError(f"unknown strategy: {strategy}")
    return mid


@pytest.mark.parametrize("strategy", ["time_expiry", "noise", "episodic"])
async def test_pruning_rides_every_forgetting_strategy(engine, entity_id, strategy):
    """Every strategy prunes edges and orphan nodes via the shared seam."""
    mid = await _ingest_and_forget(engine, entity_id, strategy)
    assert await engine.graph.get_memory_mentions(mid) == []
    assert await engine.graph.get_entity_mentions(entity_id) == []


async def test_updates_replacement_keeps_historical_mentions(engine, entity_id):
    """The UPDATES path (update_is_latest) keeps mention edges (#26 guard)."""
    old_mid = await add_content(engine, entity_id, GOOGLE_ENTRY[0])
    new_mid = await add_content(engine, entity_id, GUGE_ENTRY[0])

    await engine.graph.update_is_latest(old_mid, False, replaced_by=new_mid)

    # The replaced memory is history, but its MENTIONS edges stay; the
    # shared node still counts both live edges.
    old_mentions = await engine.graph.get_memory_mentions(old_mid)
    assert [m["canonical_form"] for m in old_mentions] == ["Google"]
    nodes = await engine.graph.get_entity_mentions(entity_id)
    assert len(nodes) == 1
    assert nodes[0]["mention_count"] == 2
