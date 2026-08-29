"""Unit tests for the B6 mark_consolidated seam (T2, issue #43).

The seam under test is ``GraphStore.mark_consolidated`` on the in-memory
backend: atomic disposal (is_latest=false + replaced_by=representative +
expired_at + metadata reason=consolidated), MENTIONS / EXTENDS /
DERIVES_FROM edge rewiring to the representative (mention_count
recomputed), no representative→merged UPDATES edge, representative
untouched, and every no-op / guard case. Per the ticket's acceptance
criteria the suite asserts the observable graph state after the call —
never implementation internals.
"""

from __future__ import annotations

import pytest

from emerald.core.graph import GraphStore
from emerald.core.mentions import Mention


@pytest.fixture
def graph() -> GraphStore:
    return GraphStore(use_db=False)


async def _mem(
    graph: GraphStore,
    entity_id: str,
    content: str,
    *,
    memory_type: str = "fact",
    confidence: float = 0.4,
    metadata: dict | None = None,
) -> str:
    return await graph.create_memory(
        content,
        entity_id=entity_id,
        memory_type=memory_type,
        confidence=confidence,
        metadata=metadata,
    )


async def _mention(
    graph: GraphStore,
    memory_id: str,
    entity_id: str,
    canonical: str,
    surface: str | None = None,
) -> None:
    await graph.attach_mentions(
        memory_id,
        entity_id,
        [Mention(surface or canonical, canonical, "concept", 0.9)],
    )


def _rel_ids(
    neighbors: dict[str, list[dict]],
    mid: str,
    *,
    rel_type: str | None = None,
) -> set[str]:
    """The neighbor ids of ``mid`` in a get_relationship_neighbors result."""
    out: set[str] = set()
    for edge in neighbors.get(mid, []):
        if rel_type is None or edge["rel_type"] == rel_type:
            out.add(edge["id"])
    return out


# ---- atomic disposal ----


@pytest.mark.asyncio
async def test_merged_memory_archived_with_representative_link(graph):
    """Disposal: is_latest=false, replaced_by=representative, expired_at
    set, metadata records reason=consolidated."""
    rep = await _mem(graph, "e1", "用户住在北京")
    merged = await _mem(graph, "e1", "用户住在北京")

    await graph.mark_consolidated(merged, rep, reason="consolidated")

    memory = await graph.get_memory(merged)
    assert memory["is_latest"] is False
    assert memory["replaced_by"] == rep
    assert memory["expired_at"] is not None
    assert memory["metadata"]["reason"] == "consolidated"


@pytest.mark.asyncio
async def test_metadata_reason_preserves_existing_metadata(graph):
    """Existing metadata survives; reason is merged in, not replacing."""
    rep = await _mem(graph, "e1", "用户住在北京")
    merged = await _mem(graph, "e1", "用户住在北京", metadata={"source": "conversation"})

    await graph.mark_consolidated(merged, rep)

    memory = await graph.get_memory(merged)
    assert memory["metadata"]["source"] == "conversation"
    assert memory["metadata"]["reason"] == "consolidated"


@pytest.mark.asyncio
async def test_representative_untouched(graph):
    """The representative keeps is_latest=true, replaced_by=None,
    expired_at=None and its own metadata."""
    rep = await _mem(graph, "e1", "用户住在北京", metadata={"keep": 1})
    merged = await _mem(graph, "e1", "用户住在北京")

    await graph.mark_consolidated(merged, rep)

    memory = await graph.get_memory(rep)
    assert memory["is_latest"] is True
    assert memory["replaced_by"] is None
    assert memory["expired_at"] is None
    assert memory["metadata"] == {"keep": 1}


@pytest.mark.asyncio
async def test_no_updates_edge_created(graph):
    """Consolidation must NOT create a representative→merged UPDATES edge
    (spec #41: otherwise multi-hop retrieval would float the duplicates
    back up)."""
    rep = await _mem(graph, "e1", "用户住在北京")
    merged = await _mem(graph, "e1", "用户住在北京")

    await graph.mark_consolidated(merged, rep)

    neighbors = await graph.get_relationship_neighbors([rep, merged], ["UPDATES"])
    assert neighbors == {}


# ---- MENTIONS rewiring ----


@pytest.mark.asyncio
async def test_mentions_rewired_to_representative(graph):
    """The merged memory's MENTIONS edges move to the representative; the
    inverted index resolves to the representative only; mention_count is
    preserved."""
    rep = await _mem(graph, "e1", "用户住在北京")
    merged = await _mem(graph, "e1", "用户住在北京")
    await _mention(graph, merged, "e1", "北京")

    await graph.mark_consolidated(merged, rep)

    rep_mentions = await graph.get_memory_mentions(rep)
    assert [m["canonical_form"] for m in rep_mentions] == ["北京"]
    assert rep_mentions[0]["mention_count"] == 1
    assert await graph.get_memory_mentions(merged) == []

    # Inverted index: only the representative (latest) surfaces.
    referencing = await graph.get_memories_mentioning("e1", "北京")
    assert [m["id"] for m in referencing] == [rep]


@pytest.mark.asyncio
async def test_mention_dedup_when_representative_already_mentions(graph):
    """Same mention node + same surface form on both sides: the edge moves
    into the representative's existing edge (no duplicate), mention_count
    decrements by exactly one."""
    rep = await _mem(graph, "e1", "用户住在北京")
    merged = await _mem(graph, "e1", "用户住在北京")
    other = await _mem(graph, "e1", "北京天气很好")
    await _mention(graph, rep, "e1", "北京")
    await _mention(graph, merged, "e1", "北京")
    await _mention(graph, other, "e1", "北京")

    await graph.mark_consolidated(merged, rep)

    rep_mentions = await graph.get_memory_mentions(rep)
    assert len(rep_mentions) == 1
    assert rep_mentions[0]["mention_count"] == 2  # rep + other

    nodes = await graph.get_entity_mentions("e1")
    assert {n["canonical_form"]: n["mention_count"] for n in nodes} == {"北京": 2}


@pytest.mark.asyncio
async def test_different_surface_forms_keep_separate_edges(graph):
    """Different surface forms of the same mention node are NOT deduped —
    both edges move to the representative (aliases preserved)."""
    rep = await _mem(graph, "e1", "用户住在北京")
    merged = await _mem(graph, "e1", "用户住在北京")
    await _mention(graph, rep, "e1", "北京", surface="北京")
    await _mention(graph, merged, "e1", "北京", surface="首都")

    await graph.mark_consolidated(merged, rep)

    rep_mentions = await graph.get_memory_mentions(rep)
    assert {m["surface_form"] for m in rep_mentions} == {"北京", "首都"}
    assert all(m["mention_count"] == 2 for m in rep_mentions)


# ---- EXTENDS / DERIVES_FROM rewiring ----


@pytest.mark.asyncio
async def test_extends_outbound_rewired(graph):
    """merged→other EXTENDS becomes rep→other EXTENDS."""
    rep = await _mem(graph, "e1", "用户住在北京")
    merged = await _mem(graph, "e1", "用户住在北京")
    other = await _mem(graph, "e1", "北京有地铁")
    await graph.create_relationship(merged, other, "EXTENDS", {"aspect": "detail"})

    await graph.mark_consolidated(merged, rep)

    assert _rel_ids(await graph.get_relationship_neighbors([merged], ["EXTENDS"]), merged) == set()
    assert _rel_ids(await graph.get_relationship_neighbors([rep], ["EXTENDS"]), rep) == {other}
    assert _rel_ids(await graph.get_relationship_neighbors([other], ["EXTENDS"]), other) == {rep}


@pytest.mark.asyncio
async def test_extends_inbound_rewired(graph):
    """other→merged EXTENDS becomes other→rep EXTENDS."""
    rep = await _mem(graph, "e1", "用户住在北京")
    merged = await _mem(graph, "e1", "用户住在北京")
    other = await _mem(graph, "e1", "用户也喜欢上海")
    await graph.create_relationship(other, merged, "EXTENDS")

    await graph.mark_consolidated(merged, rep)

    assert _rel_ids(await graph.get_relationship_neighbors([merged], ["EXTENDS"]), merged) == set()
    assert _rel_ids(await graph.get_relationship_neighbors([other], ["EXTENDS"]), other) == {rep}


@pytest.mark.asyncio
async def test_derives_from_rewired_both_directions(graph):
    """DERIVES_FROM rewires both ways like EXTENDS."""
    rep = await _mem(graph, "e1", "用户住在北京")
    merged = await _mem(graph, "e1", "用户住在北京")
    source = await _mem(graph, "e1", "用户说住在北京")
    derived = await _mem(graph, "e1", "用户常驻北京")
    await graph.create_relationship(merged, source, "DERIVES_FROM", {"reasoning": "combined"})
    await graph.create_relationship(derived, merged, "DERIVES_FROM")

    await graph.mark_consolidated(merged, rep)

    out = await graph.get_relationship_neighbors([rep, merged], ["DERIVES_FROM"])
    assert _rel_ids(out, rep) == {source, derived}  # outbound + inbound both rewire
    assert _rel_ids(out, merged) == set()
    assert _rel_ids(
        await graph.get_relationship_neighbors([derived], ["DERIVES_FROM"]), derived
    ) == {rep}


@pytest.mark.asyncio
async def test_relationship_properties_preserved(graph):
    """Rewired edges keep their properties (aspect / confidence)."""
    rep = await _mem(graph, "e1", "用户住在北京")
    merged = await _mem(graph, "e1", "用户住在北京")
    other = await _mem(graph, "e1", "北京有地铁")
    await graph.create_relationship(
        merged, other, "EXTENDS", {"aspect": "detail", "confidence": 0.7}
    )

    await graph.mark_consolidated(merged, rep)

    rel = await graph.get_relationship_by_property("EXTENDS", "aspect", "detail")
    assert rel is not None
    assert rel["from_id"] == rep
    assert rel["to_id"] == other
    assert rel["aspect"] == "detail"
    assert rel["confidence"] == 0.7


@pytest.mark.asyncio
async def test_each_rewired_edge_moves_exactly_once(graph):
    """A merged memory with several mentions and several EXTENDS edges
    rewires each edge exactly once — no duplicates (the Cypher branch
    must not multiply rows across rewiring segments)."""
    rep = await _mem(graph, "e1", "用户住在北京")
    merged = await _mem(graph, "e1", "用户住在北京")
    other = await _mem(graph, "e1", "北京有地铁")
    await _mention(graph, merged, "e1", "北京")
    await _mention(graph, merged, "e1", "地铁")
    await graph.create_relationship(merged, other, "EXTENDS")
    await graph.create_relationship(other, merged, "DERIVES_FROM")

    await graph.mark_consolidated(merged, rep)

    out = await graph.get_relationship_neighbors([rep, other], ["EXTENDS", "DERIVES_FROM"])
    # Exactly one EXTENDS edge rep→other and one DERIVES_FROM edge
    # other→rep — no duplicate edges from multi-mention input.
    extends = [e for e in out.get(rep, []) if e["rel_type"] == "EXTENDS"]
    derives = [e for e in out.get(other, []) if e["rel_type"] == "DERIVES_FROM"]
    assert [e["id"] for e in extends] == [other]
    assert [e["id"] for e in derives] == [rep]


# ---- UPDATES edges untouched ----


@pytest.mark.asyncio
async def test_updates_edges_untouched(graph):
    """Existing UPDATES edges are neither rewired nor deleted: a source
    keeps UPDATES→merged, a target keeps merged→it (timeline chains to
    history survive)."""
    rep = await _mem(graph, "e1", "用户住在北京")
    merged = await _mem(graph, "e1", "用户住在北京")
    source = await _mem(graph, "e1", "用户住在上海")
    target = await _mem(graph, "e1", "用户住在南京")
    # source UPDATES merged (source is newer), merged UPDATES target.
    await graph.create_relationship(source, merged, "UPDATES")
    await graph.create_relationship(merged, target, "UPDATES")

    await graph.mark_consolidated(merged, rep)

    neighbors = await graph.get_relationship_neighbors([merged], ["UPDATES"])
    assert _rel_ids(neighbors, merged) == {source, target}


# ---- self-loop guard ----


@pytest.mark.asyncio
async def test_no_self_loop_when_representative_is_neighbor(graph):
    """An EXTENDS edge between the pair (rep→merged or merged→rep) is
    left as-is, never re-pointed onto the representative itself."""
    rep = await _mem(graph, "e1", "用户住在北京")
    merged = await _mem(graph, "e1", "用户住在北京")
    await graph.create_relationship(rep, merged, "EXTENDS")
    await graph.create_relationship(merged, rep, "EXTENDS")

    await graph.mark_consolidated(merged, rep)

    rep_neighbors = await graph.get_relationship_neighbors([rep], ["EXTENDS"])
    assert _rel_ids(rep_neighbors, rep) == {merged}  # rep→merged survives; no rep→rep
    merged_neighbors = await graph.get_relationship_neighbors([merged], ["EXTENDS"])
    assert _rel_ids(merged_neighbors, merged) == {rep}


@pytest.mark.asyncio
async def test_multihop_path_preserved_through_representative(graph):
    """A path rep—merged—other collapses to rep—other: multi-hop
    retrieval still reaches other after consolidation."""
    rep = await _mem(graph, "e1", "用户住在北京")
    merged = await _mem(graph, "e1", "用户住在北京")
    other = await _mem(graph, "e1", "北京有地铁")
    await graph.create_relationship(rep, merged, "EXTENDS")
    await graph.create_relationship(merged, other, "EXTENDS")

    await graph.mark_consolidated(merged, rep)

    rep_neighbors = await graph.get_relationship_neighbors([rep], ["EXTENDS"])
    assert _rel_ids(rep_neighbors, rep) == {merged, other}


# ---- no-op and guard cases ----


@pytest.mark.asyncio
async def test_missing_merged_memory_is_noop(graph):
    rep = await _mem(graph, "e1", "用户住在北京")
    await graph.mark_consolidated("does-not-exist", rep)
    assert (await graph.get_memory(rep))["is_latest"] is True


@pytest.mark.asyncio
async def test_missing_representative_is_noop(graph):
    merged = await _mem(graph, "e1", "用户住在北京")
    await graph.mark_consolidated(merged, "does-not-exist")
    memory = await graph.get_memory(merged)
    assert memory["is_latest"] is True
    assert memory["replaced_by"] is None


@pytest.mark.asyncio
async def test_already_historical_merged_is_noop(graph):
    """A merged memory that is already historical is left untouched —
    idempotent re-runs never double-archive or rewire."""
    rep = await _mem(graph, "e1", "用户住在北京")
    merged = await _mem(graph, "e1", "用户住在北京")
    await graph.mark_consolidated(merged, rep)
    original = dict(await graph.get_memory(merged))
    await _mention(graph, merged, "e1", "北京")  # a late edge must stay put

    await graph.mark_consolidated(merged, rep)

    memory = await graph.get_memory(merged)
    assert memory["replaced_by"] == original["replaced_by"] == rep
    assert memory["expired_at"] == original["expired_at"]
    assert [m["canonical_form"] for m in await graph.get_memory_mentions(merged)] == ["北京"]


@pytest.mark.asyncio
async def test_self_consolidation_raises(graph):
    rep = await _mem(graph, "e1", "用户住在北京")
    with pytest.raises(ValueError):
        await graph.mark_consolidated(rep, rep)


@pytest.mark.asyncio
async def test_cross_entity_isolation_preserved(graph):
    """A representative in another entity never receives the merged
    memory's edges (ADR-0002) — the no-op path keeps both entities
    untouched."""
    rep = await _mem(graph, "e1", "用户住在北京")
    merged = await _mem(graph, "e2", "用户住在北京")
    await _mention(graph, merged, "e2", "北京")

    await graph.mark_consolidated(merged, rep)

    # merged stays latest (the representative is not in its entity)
    assert (await graph.get_memory(merged))["is_latest"] is True
    assert [m["canonical_form"] for m in await graph.get_memory_mentions(merged)] == ["北京"]
    assert await graph.get_memory_mentions(rep) == []
