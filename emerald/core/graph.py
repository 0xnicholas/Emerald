"""Graph store — Neo4j operations for memory nodes and relationships.

Manages the knowledge graph: creates Memory nodes, links them to Entity nodes,
queries latest memories, and supports relationship operations.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import structlog

logger = structlog.get_logger(__name__)


class GraphStore:
    """Manages memory storage in the Neo4j knowledge graph.

    In production uses the Neo4j async driver. For testing without a
    database, an in-memory fallback is available.
    """

    def __init__(self, use_db: bool = True) -> None:
        self._use_db = use_db
        self._driver = None
        if use_db:
            try:
                from emerald.db.neo4j import get_neo4j_driver
                self._driver = get_neo4j_driver()
            except RuntimeError:
                # Driver not initialized — silently fall back to in-memory
                self._use_db = False
        # In-memory store: entity_id → list of memory dicts
        self._memories: dict[str, list[dict[str, Any]]] = {}

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
        valid_until: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Create a Memory node linked to an Entity.

        Returns the memory ID.
        """
        memory_id = uuid4().hex
        now = datetime.now(UTC)

        import json

        metadata_json = json.dumps(metadata) if metadata else None

        if self._use_db and self._driver:
            async with self._driver.session() as session:
                await session.run(
                    """
                    MERGE (e:Entity {id: $entity_id})
                    ON CREATE SET e.created_at = datetime(), e.type = "user"
                    CREATE (m:Memory {
                        id: $id, content: $content, summary: $summary,
                        memory_type: $memory_type, confidence: $confidence,
                        is_latest: true, valid_from: datetime(),
                        valid_until: datetime($valid_until),
                        replaced_by: null,
                        source_document_id: $document_id,
                        source_type: $source_type,
                        tokens_estimate: $tokens,
                        access_count: 0,
                        last_accessed_at: null,
                        created_at: datetime(),
                        updated_at: datetime(),
                        metadata: $metadata
                    })
                    CREATE (e)-[:HAS_MEMORY {created_at: datetime()}]->(m)
                    """,
                    id=memory_id,
                    content=content,
                    entity_id=entity_id,
                    summary=summary or content[:200],
                    memory_type=memory_type,
                    confidence=confidence,
                    valid_until=valid_until.isoformat() if valid_until else None,
                    document_id=document_id,
                    source_type=source_type,
                    tokens=len(content) // 4,
                    metadata=metadata_json,
                )
        else:
            memory = {
                "id": memory_id,
                "content": content,
                "summary": summary or content[:200],
                "memory_type": memory_type,
                "confidence": confidence,
                "is_latest": True,
                "valid_from": now,
                "valid_until": valid_until,
                "expired_at": None,
                "replaced_by": None,
                "source_document_id": document_id,
                "source_type": source_type,
                "tokens_estimate": len(content) // 4,
                "access_count": 0,
                "last_accessed_at": None,
                "created_at": now,
                "updated_at": now,
                "metadata": metadata,
            }
            self._memories.setdefault(entity_id, []).append(memory)

        logger.info(
            "graph.memory.created",
            memory_id=memory_id,
            entity_id=entity_id,
            memory_type=memory_type,
        )
        return memory_id

    async def get_memory(self, memory_id: str) -> dict[str, Any] | None:
        """Get a single memory by ID."""
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                result = await session.run(
                    "MATCH (m:Memory {id: $id}) RETURN m", id=memory_id
                )
                record = await result.single()
                if record:
                    return dict(record["m"])
                return None

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
    ) -> list[dict[str, Any]]:
        """List latest (is_latest=True, not expired) memories for an entity.

        Ordered by created_at descending.
        """
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    MATCH (e:Entity {id: $entity_id})-[:HAS_MEMORY]->(m:Memory)
                    WHERE m.is_latest = true
                      AND (m.valid_until IS NULL OR m.valid_until > datetime())
                    RETURN m
                    ORDER BY m.created_at DESC
                    LIMIT $limit
                    """,
                    entity_id=entity_id,
                    limit=limit,
                )
                memories = []
                async for record in result:
                    memories.append(dict(record["m"]))
                if memory_type:
                    memories = [m for m in memories if m.get("memory_type") == memory_type]
                return memories

        memories = self._memories.get(entity_id, [])
        now = datetime.now(UTC)
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

    async def update_is_latest(
        self, memory_id: str, is_latest: bool, replaced_by: str | None = None
    ) -> None:
        """Set the is_latest flag on a memory, optionally recording what replaced it."""
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                await session.run(
                    """
                    MATCH (m:Memory {id: $id})
                    SET m.is_latest = $is_latest,
                        m.replaced_by = $replaced_by,
                        m.updated_at = datetime()
                    """,
                    id=memory_id,
                    is_latest=is_latest,
                    replaced_by=replaced_by,
                )
            return

        for memories in self._memories.values():
            for m in memories:
                if m["id"] == memory_id:
                    m["is_latest"] = is_latest
                    m["updated_at"] = datetime.now(UTC)
                    if replaced_by is not None:
                        m["replaced_by"] = replaced_by
                    return
