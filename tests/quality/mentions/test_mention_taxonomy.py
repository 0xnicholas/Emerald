"""Quality suite section 4c — closed taxonomy + confidence gating (#24).

B3 T3 asserts, on the deterministic rule-only path:

- every extracted mention type falls inside the closed taxonomy
  (person / organization / location / technology / datetime / role /
  concept) — types are consistent and filterable (spec #21 user story 18)
- a mention type outside the taxonomy falls back to concept — no
  malformed nodes (story 18)
- a mention below the confidence threshold produces no Mention node and
  no MENTIONS edge — the memory still ingests (story 19 + graceful
  degradation)
- a mention exactly at the threshold is kept (boundary is inclusive)

Deterministic labelled corpus + mock embeddings + rule-only path, same
fixtures as sections 4 (#22) and 4b (#23).
"""

from __future__ import annotations

import pytest

from emerald.core.mentions import (
    MENTION_CONFIDENCE_THRESHOLD,
    VALID_MENTION_TYPES,
)
from tests.quality.mentions.conftest import add_content, make_engine
from tests.quality.mentions.corpus import HAPPY_PATH_CORPUS

pytestmark = [pytest.mark.quality]

# A gazetteer entry with a type outside the closed taxonomy: the rule path
# extracts it as-is; the graph layer must fall back to concept (#24).
INVALID_TYPE_GAZETTEER = {"unicorn": ("Unicorn", "fictional_beast")}




async def test_extracted_types_stay_inside_closed_taxonomy(engine, entity_id):
    """Every corpus mention's type is a member of the closed taxonomy."""
    for content, expected in HAPPY_PATH_CORPUS:
        result = await engine.add(content, entity_id=entity_id)
        assert len(result.memory_ids) == 1
        mentions = await engine.graph.get_memory_mentions(result.memory_ids[0])
        assert len(mentions) == len(expected)
        for mention in mentions:
            assert mention["type"] in VALID_MENTION_TYPES, (
                f"type {mention['type']!r} outside the closed taxonomy"
            )


async def test_invalid_type_falls_back_to_concept(engine, entity_id):
    """A type outside the taxonomy becomes concept — no malformed nodes."""
    engine = make_engine(gazetteer=INVALID_TYPE_GAZETTEER)
    mid = await add_content(engine, entity_id, "用户见到了 unicorn")

    mentions = await engine.graph.get_memory_mentions(mid)
    assert len(mentions) == 1
    assert mentions[0]["canonical_form"] == "Unicorn"
    assert mentions[0]["type"] == "concept"
    # The stored node carries the normalized type, in the entity pool.
    pool = engine.graph._mentions.get(entity_id, [])
    assert len(pool) == 1
    assert pool[0]["type"] == "concept"


async def test_datetime_role_concept_types_pass_through(engine, entity_id):
    """The remaining three taxonomy classes classify positively.

    Together with the corpus (technology/organization/person/location),
    this exercises all seven closed-taxonomy classes.
    """
    engine = make_engine(
        gazetteer={
            "明天": ("明天", "datetime"),
            "CTO": ("CTO", "role"),
            "哲学": ("哲学", "concept"),
        },
    )
    mid = await add_content(engine, entity_id, "明天 CTO 讨论哲学")

    mentions = await engine.graph.get_memory_mentions(mid)
    assert [(m["canonical_form"], m["type"]) for m in mentions] == [
        ("明天", "datetime"),
        ("CTO", "role"),
        ("哲学", "concept"),
    ]


async def test_low_confidence_mentions_are_dropped(engine, entity_id):
    """Below-threshold mentions create no node and no edge; ingestion OK."""
    engine = make_engine(confidence=MENTION_CONFIDENCE_THRESHOLD - 0.1)
    content, expected = HAPPY_PATH_CORPUS[4]  # two mentions, both gated
    assert expected, "corpus entry must carry mentions for this test"
    mid = await add_content(engine, entity_id, content)

    memory = await engine.graph.get_memory(mid)
    assert memory["is_latest"] is True  # gating never fails ingestion
    assert await engine.graph.get_memory_mentions(mid) == []
    assert engine.graph._mentions.get(entity_id, []) == []
    assert memory.get("mentions", []) == []


async def test_at_threshold_mentions_are_kept(engine, entity_id):
    """The confidence boundary is inclusive: threshold == keep."""
    engine = make_engine(confidence=MENTION_CONFIDENCE_THRESHOLD)
    mid = await add_content(engine, entity_id, HAPPY_PATH_CORPUS[1][0])

    mentions = await engine.graph.get_memory_mentions(mid)
    assert len(mentions) == 1
    assert mentions[0]["canonical_form"] == "Google"
    assert mentions[0]["confidence"] == MENTION_CONFIDENCE_THRESHOLD
