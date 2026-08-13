"""Multihop traversal engine (B4) — graph-walking beyond vector similarity.

B4 T2 (#31): shared-subject bridging — from a seed memory, walk
Memory-MENTIONS->Mention<-MENTIONS-Memory so that different memories
about the same canonical thing surface together, regardless of wording.

Design (spec #29):
- The engine is an internal graph walker; SearchOrchestrator owns
  ranking and result shaping.
- Bridging is entity-scoped: ``get_memory_mentions`` + the entity-scoped
  ``get_memories_mentioning`` are the only traversal primitives, so a
  hop can never leave the entity's context pool.
- Type participates in the bridge: mentions resolve to (entity_id,
  canonical_form, type) nodes (B3 T2), so "Apple" the organization and
  "Apple" the technology are different nodes and never bridge.
- Cycle-safe: a visited set of memory ids bounds every walk; each
  memory appears at its shallowest depth only.
- Historical memories (is_latest=false) are never bridged to — plain
  traversal does not reach into history (spec #29: 不主动搜历史).
- Relationship chains (UPDATES / EXTENDS / DERIVES_FROM) land in #32;
  this ticket walks MENTIONS bridges only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from emerald.core.graph import GraphStore

logger = structlog.get_logger(__name__)

# Spec #29: depth 上限 4；默认 0（现状语义，显式 opt-in — issue #33）。
MAX_DEPTH = 4


@dataclass
class Hop:
    """A memory reached by the walk, with provenance.

    ``path`` interleaves (kind, id) steps from the seed memory through
    Mention nodes to the bridged memory, e.g.
    [("memory", seed), ("mention", mn1), ("memory", bridged)].
    """

    memory_id: str
    depth: int
    path: list[tuple[str, str]] = field(default_factory=list)


class MultihopEngine:
    """BFS over the mention graph from a seed set of memories."""

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
        shallowest depth (cycle safety). depth <= 0 returns nothing —
        depth=0 is the status quo (spec #29 / ticket #31).
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
                # The memory's mention nodes (its MENTIONS edges).
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
