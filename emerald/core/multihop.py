"""Multihop traversal engine (B4) — graph-walking beyond vector similarity.

B4 T2 (#31): shared-subject bridging — from a seed memory, walk
Memory-MENTIONS->Mention<-MENTIONS-Memory so that different memories
about the same canonical thing surface together, regardless of wording.

B4 T3 (#32): relationship chains — one hop may also walk
UPDATES / EXTENDS / DERIVES_FROM bidirectionally, and a reached memory
participates in the next hop (D2 -DF-> D1 -DF-> A surfaces D2 at depth
2 from A).

Design (spec #29):
- The engine is an internal graph walker; SearchOrchestrator owns
  ranking and result shaping.
- Every hop is entity-scoped: mention methods are entity-scoped at the
  graph seam, and relationship neighbors are filtered by entity_id here,
  so a hop can never leave the entity's context pool.
- Type participates in the bridge: mentions resolve to (entity_id,
  canonical_form, type) nodes (B3 T2), so "Apple" the organization and
  "Apple" the technology are different nodes and never bridge.
- Cycle-safe: a visited set of memory ids bounds every walk; each
  memory appears at its shallowest depth only.
- History is never searched proactively: historical memories
  (is_latest=false) are not bridged to via mentions and are skipped on
  EXTENDS/DERIVES_FROM edges. Only an UPDATES edge surfaces them, marked
  ``historical``; they are terminals — never expanded further.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from emerald.core.graph import GraphStore

logger = structlog.get_logger(__name__)

# Spec #29: depth 上限 4；默认 0（现状语义，显式 opt-in — issue #33）。
MAX_DEPTH = 4

# Relationship edges the walk follows in both directions (B4, #32).
RELATIONSHIP_TYPES = ["UPDATES", "EXTENDS", "DERIVES_FROM"]


@dataclass
class Hop:
    """A memory reached by the walk, with provenance.

    ``path`` interleaves (kind, id) steps from the seed memory: a mention
    bridge contributes ("mention", node_id) then ("memory", memory_id); a
    relationship step contributes (rel_type, memory_id) — e.g.
    [("memory", seed), ("DERIVES_FROM", d1), ("DERIVES_FROM", d2)].

    ``historical`` is True when the memory was reached along an UPDATES
    edge and is_latest is false (spec #29: surfaced, marked, terminal).
    """

    memory_id: str
    depth: int
    path: list[tuple[str, str]] = field(default_factory=list)
    historical: bool = False


class MultihopEngine:
    """BFS over the mention graph and relationship edges from a seed set."""

    def __init__(self, graph: GraphStore | None = None) -> None:
        self.graph = graph or GraphStore(use_db=False)

    async def expand(
        self,
        seed_ids: list[str],
        entity_id: str,
        depth: int,
    ) -> dict[str, Hop]:
        """Return {memory_id: Hop} reachable within ``depth`` hops.

        Seeds are never part of the result; memories are keyed at their
        shallowest depth (cycle safety). One hop is a mention bridge
        (memory → shared mention → sibling memory) or one relationship
        edge (UPDATES / EXTENDS / DERIVES_FROM, both directions).
        Historical nodes surface only along UPDATES edges and are never
        expanded further. depth <= 0 returns nothing — depth=0 is the
        status quo (spec #29 / ticket #31).
        """
        if depth < 1 or not seed_ids:
            return {}

        depth = min(depth, MAX_DEPTH)
        found: dict[str, Hop] = {}
        visited: set[str] = set(seed_ids)
        # Frontier: (memory_id, depth, path-so-far from the seed).
        frontier: list[tuple[str, int, list[tuple[str, str]]]] = [
            (mid, 0, [("memory", mid)]) for mid in seed_ids
        ]

        for level in range(1, depth + 1):
            next_frontier: list[tuple[str, int, list[tuple[str, str]]]] = []
            for mid, _level, path in frontier:
                # Shared-subject bridge (B4, #31): the memory's mention
                # nodes → sibling memories referencing the same node.
                mentions = await self.graph.get_memory_mentions(mid)
                for mention in mentions:
                    # Sibling memories referencing the same mention node,
                    # entity-scoped and latest-only (graph method contract).
                    siblings = await self.graph.get_memories_mentioning(
                        entity_id,
                        mention["id"],
                        # Dense mention graphs fan out; the depth bound keeps
                        # the walk finite, so don't silently cap siblings at
                        # the read method's default page.
                        limit=1000,
                    )
                    for sibling in siblings:
                        sibling_id = sibling["id"]
                        if sibling_id in visited:
                            continue
                        visited.add(sibling_id)
                        new_path = path + [
                            ("mention", mention["id"]),
                            ("memory", sibling_id),
                        ]
                        found[sibling_id] = Hop(
                            memory_id=sibling_id,
                            depth=level,
                            path=new_path,
                        )
                        next_frontier.append((sibling_id, level, new_path))

                # Relationship edges (B4, #32): bidirectional walk along
                # UPDATES / EXTENDS / DERIVES_FROM.
                neighbors = await self.graph.get_relationship_neighbors(
                    [mid], RELATIONSHIP_TYPES,
                )
                for neighbor in neighbors.get(mid, []):
                    neighbor_id = neighbor["id"]
                    if neighbor_id in visited:
                        continue
                    # Entity isolation at every hop (spec #29 story 6).
                    if neighbor.get("entity_id") != entity_id:
                        continue
                    rel_type = neighbor["rel_type"]
                    historical = not neighbor.get("is_latest", True)
                    if historical and rel_type != "UPDATES":
                        # 不主动搜历史：EXTENDS/DERIVES_FROM never reach
                        # into history; only UPDATES surfaces it.
                        continue
                    visited.add(neighbor_id)
                    new_path = path + [(rel_type, neighbor_id)]
                    found[neighbor_id] = Hop(
                        memory_id=neighbor_id,
                        depth=level,
                        path=new_path,
                        historical=historical,
                    )
                    if not historical:
                        # Historical nodes are terminals: surfaced along
                        # the UPDATES chain, never walked through.
                        next_frontier.append((neighbor_id, level, new_path))
            frontier = next_frontier
            if not frontier:
                break

        logger.info(
            "multihop.expand",
            entity_id=entity_id,
            seeds=len(seed_ids),
            depth=min(depth, level),
            bridged=len(found),
        )
        return found
