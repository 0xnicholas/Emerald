"""Graph store — Neo4j operations for memory nodes and relationships.

Manages the knowledge graph: creates Memory nodes, links them to Entity nodes,
queries latest memories, and supports relationship operations.
"""

from __future__ import annotations

import structlog
from datetime import datetime, timezone
from uuid import uuid4

logger = structlog.get_logger(__name__)


class GraphStore:
    """Manages memory storage in the Neo4j knowledge graph.

    In production uses the Neo4j async driver. For testing without a
    database, an in-memory fallback is available.
    """

    def __init__(self, use_db: bool = True) -> None:
        self._use_db = use_db
        # In-memory store: entity_id → list of memory dicts
        self._memories: dict[str, list[dict]] = {}

    async def create_memory(
        self,
        content: str,
        *,
        entity_id: str,
        memory_type: str = "fact",
        confidence: float = 0.8,
        summary: str | None = None,
        source_type: str = "conversation",
        document_id: str | None = None,
    ) -> str:
        """Create a Memory node linked to an Entity.

        Returns the memory ID.
        """
        memory_id = uuid4().hex
        now = datetime.now(timezone.utc)

        if self._use_db:
            # TODO: Neo4j async session
            # MATCH (e:Entity {id: $entity_id})
            # CREATE (m:Memory {...}) CREATE (e)-[:HAS_MEMORY]->(m)
            pass
        else:
            memory = {
                "id": memory_id,
                "content": content,
                "summary": summary or content[:200],
                "memory_type": memory_type,
                "confidence": confidence,
                "is_latest": True,
                "valid_from": now,
                "valid_until": None,
                "expired_at": None,
                "replaced_by": None,
                "source_document_id": document_id,
                "source_type": source_type,
                "tokens_estimate": len(content) // 4,
                "access_count": 0,
                "last_accessed_at": None,
                "created_at": now,
                "updated_at": now,
            }
            self._memories.setdefault(entity_id, []).append(memory)

        logger.info(
            "graph.memory.created",
            memory_id=memory_id,
            entity_id=entity_id,
            memory_type=memory_type,
        )
        return memory_id

    async def get_memory(self, memory_id: str) -> dict | None:
        """Get a single memory by ID."""
        for entity_memories in self._memories.values():
            for m in entity_memories:
                if m["id"] == memory_id:
                    return m
        return None

    async def list_latest_memories(
        self,
        entity_id: str,
        *,
        limit: int = 50,
        memory_type: str | None = None,
    ) -> list[dict]:
        """List latest (is_latest=True, not expired) memories for an entity.

        Ordered by created_at descending.
        """
        if self._use_db:
            # TODO: Neo4j query
            # MATCH (e:Entity {id: $entity_id})-[:HAS_MEMORY]->(m:Memory)
            # WHERE m.is_latest = true
            #   AND (m.valid_until IS NULL OR m.valid_until > datetime())
            # return []
            pass

        memories = self._memories.get(entity_id, [])
        now = datetime.now(timezone.utc)
        latest = [
            m
            for m in memories
            if m["is_latest"]
            and (m["valid_until"] is None or m["valid_until"] > now)
        ]
        if memory_type:
            latest = [m for m in latest if m["memory_type"] == memory_type]

        latest.sort(key=lambda m: m["created_at"], reverse=True)
        return latest[:limit]

    async def update_is_latest(self, memory_id: str, is_latest: bool, replaced_by: str | None = None) -> None:
        """Set the is_latest flag on a memory, optionally recording what replaced it."""
        for memories in self._memories.values():
            for m in memories:
                if m["id"] == memory_id:
                    m["is_latest"] = is_latest
                    m["updated_at"] = datetime.now(timezone.utc)
                    if replaced_by is not None:
                        m["replaced_by"] = replaced_by
                    return
