"""Graph store — Neo4j operations for memory nodes and relationships.

Manages the knowledge graph: creates Memory nodes, links them to Entity nodes,
queries latest memories, and supports relationship operations.
"""

from __future__ import annotations

import copy
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
        # In-memory store: entity_id → list of memory dicts
        self._memories: dict[str, list[dict[str, Any]]] = {}

    def _init_driver(self) -> None:
        """Lazy-init Neo4j driver; retry on each call if not yet available."""
        if not self._use_db or self._driver is not None:
            return
        try:
            from emerald.db.neo4j import get_neo4j_driver
            self._driver = get_neo4j_driver()
        except RuntimeError:
            # Driver not initialized — silently fall back to in-memory
            self._use_db = False

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
        self._init_driver()
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
                "metadata": copy.deepcopy(metadata) if metadata is not None else None,
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
        self._init_driver()
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
        self._init_driver()
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

    async def list_recent_memories(
        self,
        *,
        since_minutes: int = 120,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """List is_latest=True memories created in the last N minutes across all entities.

        Used by ReconciliationEngine to find potentially orphaned nodes
        (created in Neo4j but missing from pgvector).
        """
        from datetime import UTC, datetime, timedelta

        cutoff = datetime.now(UTC) - timedelta(minutes=since_minutes)

        self._init_driver()
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    MATCH (m:Memory)
                    WHERE m.is_latest = true
                      AND m.created_at >= $cutoff
                    RETURN m
                    ORDER BY m.created_at DESC
                    LIMIT $limit
                    """,
                    cutoff=cutoff.isoformat(),
                    limit=limit,
                )
                memories = []
                async for record in result:
                    memories.append(dict(record["m"]))
                return memories

        # In-memory fallback: scan all entities
        memories: list[dict[str, Any]] = []
        for entity_memories in self._memories.values():
            for m in entity_memories:
                created = m.get("created_at")
                if (
                    m["is_latest"]
                    and created is not None
                    and created >= cutoff
                ):
                    memories.append(m)
        memories.sort(key=lambda m: m.get("created_at", datetime.min.replace(tzinfo=UTC)), reverse=True)
        return memories[:limit]

    async def list_forget_candidates(
        self,
        entity_id: str,
        *,
        limit: int = 1000,
        memory_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all is_latest=True memories for an entity (including expired).

        Used by ForgetEngine to scan for memories that need archiving.
        Unlike list_latest_memories, this does NOT filter out expired memories.
        """
        self._init_driver()
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    MATCH (e:Entity {id: $entity_id})-[:HAS_MEMORY]->(m:Memory)
                    WHERE m.is_latest = true
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
        latest = [m for m in memories if m["is_latest"]]
        if memory_type:
            latest = [m for m in latest if m["memory_type"] == memory_type]
        latest.sort(key=lambda m: m["created_at"], reverse=True)
        return latest[:limit]

    async def update_is_latest(
        self, memory_id: str, is_latest: bool, replaced_by: str | None = None
    ) -> None:
        """Set the is_latest flag on a memory, optionally recording what replaced it."""
        self._init_driver()
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

    async def update_memory_confidence(
        self, memory_id: str, confidence: float
    ) -> None:
        """Update the confidence score of a memory."""
        self._init_driver()
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                await session.run(
                    """
                    MATCH (m:Memory {id: $id})
                    SET m.confidence = $confidence, m.updated_at = datetime()
                    """,
                    id=memory_id,
                    confidence=confidence,
                )
            return

        for memories in self._memories.values():
            for m in memories:
                if m["id"] == memory_id:
                    m["confidence"] = confidence
                    m["updated_at"] = datetime.now(UTC)
                    return

    async def mark_expired(self, memory_id: str, reason: str = "expired") -> None:
        """Mark a memory as expired: is_latest=False + expired_at=now.

        This is a convenience wrapper used by ForgetEngine.
        """
        self._init_driver()
        now = datetime.now(UTC)
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                await session.run(
                    """
                    MATCH (m:Memory {id: $id})
                    SET m.is_latest = false,
                        m.expired_at = datetime(),
                        m.replaced_by = $reason,
                        m.updated_at = datetime()
                    """,
                    id=memory_id,
                    reason=reason,
                )
            return

        for memories in self._memories.values():
            for m in memories:
                if m["id"] == memory_id:
                    m["is_latest"] = False
                    m["expired_at"] = now
                    m["replaced_by"] = reason
                    m["updated_at"] = now
                    return

    async def create_relationship(
        self,
        from_id: str,
        to_id: str,
        rel_type: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Create a directed relationship between two memories.

        Args:
            from_id: Source memory ID.
            to_id: Target memory ID.
            rel_type: Relationship type (UPDATES, EXTENDS, DERIVES_FROM).
            properties: Optional relationship properties.
        """
        self._init_driver()
        props = properties or {}
        now = datetime.now(UTC)

        if self._use_db and self._driver:
            async with self._driver.session() as session:
                await session.run(
                    """
                    MATCH (from:Memory {id: $from_id})
                    MATCH (to:Memory {id: $to_id})
                    CREATE (from)-[r:%s {
                        created_at: datetime(),
                        confidence: $confidence,
                        reason: $reason
                    }]->(to)
                    """ % rel_type.upper(),
                    from_id=from_id,
                    to_id=to_id,
                    confidence=props.get("confidence", 0.8),
                    reason=props.get("reason", ""),
                )
            return

        # In-memory: store relationships on the target memory
        for memories in self._memories.values():
            for m in memories:
                if m["id"] == to_id:
                    rels = m.setdefault("relationships", [])
                    rels.append({
                        "from_id": from_id,
                        "type": rel_type,
                        "created_at": now,
                        **props,
                    })
                    return

    async def get_relationships_to(
        self, memory_ids: list[str]
    ) -> dict[str, list[str]]:
        """Find memories that have an UPDATES relationship TO the given memory IDs.

        Returns a dict mapping ``target_memory_id → [source_memory_ids]``.
        """
        self._init_driver()
        result: dict[str, list[str]] = {}
        if not memory_ids:
            return result

        if self._use_db and self._driver:
            async with self._driver.session() as session:
                res = await session.run(
                    """
                    MATCH (m:Memory)-[r:UPDATES]->(target:Memory)
                    WHERE target.id IN $ids
                    RETURN target.id AS target_id, m.id AS source_id
                    """,
                    ids=memory_ids,
                )
                async for record in res:
                    tid = record["target_id"]
                    sid = record["source_id"]
                    result.setdefault(tid, []).append(sid)
            return result

        # In-memory fallback
        for entity_memories in self._memories.values():
            for m in entity_memories:
                if m["id"] not in memory_ids:
                    continue
                for rel in m.get("relationships", []):
                    if rel["type"] == "UPDATES":
                        tid = m["id"]
                        sid = rel["from_id"]
                        result.setdefault(tid, []).append(sid)
        return result

    async def get_related_memories(
        self,
        memory_ids: list[str],
        rel_types: list[str] | None = None,
    ) -> dict[str, list[str]]:
        """Find memories connected via EXTENDS or DERIVES_FROM (both directions).

        Returns dict mapping ``memory_id → [related_memory_ids]``.
        Both outbound (this memory extends/derives from others) AND
        inbound (other memories extend/derive from this one) are included.
        """
        if rel_types is None:
            rel_types = ["EXTENDS", "DERIVES_FROM"]

        result: dict[str, list[str]] = {}
        id_set = set(memory_ids)

        self._init_driver()
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                res = await session.run(
                    """
                    MATCH (m:Memory)-[r]->(other:Memory)
                    WHERE m.id IN $ids AND type(r) IN $rel_types
                    RETURN m.id AS from_id, other.id AS related_id, type(r) AS rel_type
                    UNION
                    MATCH (other:Memory)-[r]->(m:Memory)
                    WHERE m.id IN $ids AND type(r) IN $rel_types
                    RETURN m.id AS from_id, other.id AS related_id, type(r) AS rel_type
                    """,
                    ids=list(id_set),
                    rel_types=rel_types,
                )
                async for record in res:
                    fid = record["from_id"]
                    rid = record["related_id"]
                    result.setdefault(fid, []).append(rid)
            return result

        # In-memory fallback: scan all memories for matching relationships
        for entity_memories in self._memories.values():
            for m in entity_memories:
                mid = m["id"]
                for rel in m.get("relationships", []):
                    if rel["type"] not in rel_types:
                        continue
                    from_id = rel["from_id"]
                    # Outbound: if this memory (mid) is a target, the source (from_id)
                    # points to it — add the source as related to this memory.
                    # Skip if source is already in the query set (caller already has it).
                    if mid in id_set and from_id not in id_set:
                        result.setdefault(mid, []).append(from_id)
                    # Inbound: if the source (from_id) is in our set, then this
                    # memory (mid) is a related target — add it.
                    # Skip if target is already in the query set.
                    if from_id in id_set and mid not in id_set:
                        result.setdefault(from_id, []).append(mid)

        # The caller handles deduplication (results may contain IDs that
        # are already in the original result set).
        return result

    async def keyword_search_memories(
        self,
        entity_id: str,
        query: str,
        top_k: int = 10,
    ) -> list[tuple[str, str, float]]:
        """Search memory content using Neo4j full-text index.

        Returns list of (memory_id, content, score).
        Falls back to in-memory scan if DB or index is unavailable.
        """
        self._init_driver()
        if self._use_db and self._driver:
            try:
                async with self._driver.session() as session:
                    result = await session.run(
                        """
                        CALL db.index.fulltext.queryNodes('memory_content', $query)
                        YIELD node, score
                        WHERE (node)-[:HAS_MEMORY]-(:Entity {id: $entity_id})
                        RETURN node.id AS id, node.content AS content, score
                        LIMIT $top_k
                        """,
                        query=query,
                        entity_id=entity_id,
                        top_k=top_k,
                    )
                    rows = []
                    async for record in result:
                        rows.append((
                            record["id"],
                            record["content"],
                            float(record["score"]),
                        ))
                    return rows
            except Exception:
                # Index may not exist or query failed — fall through
                pass

        # In-memory fallback: brute-force keyword match
        import re

        query_terms = re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]", query.lower())
        memories = self._memories.get(entity_id, [])
        results = []
        for m in memories:
            if not m.get("is_latest", True):
                continue
            content = m.get("content", "")
            if not query_terms:
                continue
            matches = sum(1 for term in query_terms if term in content.lower())
            if matches:
                score = matches / len(query_terms)
                results.append((m["id"], content, score))
        results.sort(key=lambda x: x[2], reverse=True)
        return results[:top_k]
