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
        # In-memory store: "space:{entity_id}" → list of space dicts
        self._spaces: dict[str, list[dict[str, Any]]] = {}

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
        container_tag: str = "default",
        memory_type: str = "fact",
        internal_type: str | None = None,
        confidence: float = 0.8,
        provenance: str = "explicit_statement",
        validation_count: int = 0,
        validated_at: datetime | None = None,
        contradiction_detected: bool = False,
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
                        id: $id, entity_id: $entity_id, container_tag: $container_tag,
                        content: $content,
                        summary: $summary,
                        memory_type: $memory_type, internal_type: $internal_type,
                        confidence: $confidence,
                        provenance: $provenance, validation_count: $validation_count,
                        validated_at: datetime($validated_at),
                        contradiction_detected: $contradiction_detected,
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
                    container_tag=container_tag,
                    memory_type=memory_type,
                    internal_type=internal_type,
                    confidence=confidence,
                    provenance=provenance,
                    validation_count=validation_count,
                    validated_at=validated_at.isoformat() if validated_at else None,
                    contradiction_detected=contradiction_detected,
                    valid_until=valid_until.isoformat() if valid_until else None,
                    document_id=document_id,
                    source_type=source_type,
                    tokens=len(content) // 4,
                    metadata=metadata_json,
                )
        else:
            memory = {
                "id": memory_id,
                "entity_id": entity_id,
                "container_tag": container_tag,
                "content": content,
                "summary": summary or content[:200],
                "memory_type": memory_type,
                "internal_type": internal_type,
                "confidence": confidence,
                "provenance": provenance,
                "validation_count": validation_count,
                "validated_at": validated_at,
                "contradiction_detected": contradiction_detected,
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
            provenance=provenance,
        )
        return memory_id

    async def get_memory(self, memory_id: str) -> dict[str, Any] | None:
        """Get a single memory by ID."""
        self._init_driver()
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    MATCH (e:Entity)-[:HAS_MEMORY]->(m:Memory {id: $id})
                    RETURN m, e.id AS entity_id
                    """,
                    id=memory_id,
                )
                record = await result.single()
                if record:
                    memory = dict(record["m"])
                    memory["entity_id"] = record["entity_id"]
                    return memory
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

    async def list_entity_ids(self) -> list[str]:
        """Return IDs of all entities that have at least one latest memory.

        Used by ForgetEngine to iterate across entities for time-based
        expiry, noise filtering, and episodic decay strategies.
        """
        self._init_driver()
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    MATCH (e:Entity)-[:HAS_MEMORY]->(m:Memory)
                    WHERE m.is_latest = true
                    RETURN DISTINCT e.id AS entity_id
                    """
                )
                ids: list[str] = []
                async for record in result:
                    ids.append(record["entity_id"])
                return ids

        # In-memory fallback: filter to entities with at least one latest memory
        ids: list[str] = []
        for entity_id, memories in self._memories.items():
            if any(m.get("is_latest", True) for m in memories):
                ids.append(entity_id)
        return ids

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
        memories.sort(
            key=lambda m: m.get("created_at", datetime.min.replace(tzinfo=UTC)),
            reverse=True,
        )
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

    async def update_memory(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        summary: str | None = None,
        memory_type: str | None = None,
        confidence: float | None = None,
    ) -> None:
        """Update a memory's content, summary, type, and/or confidence."""
        self._init_driver()
        sets = []
        params: dict[str, object] = {"id": memory_id}
        now = datetime.now(UTC)

        if content is not None:
            sets.append("m.content = $content")
            params["content"] = content
        if summary is not None:
            sets.append("m.summary = $summary")
            params["summary"] = summary
        if memory_type is not None:
            sets.append("m.memory_type = $memory_type")
            params["memory_type"] = memory_type
        if confidence is not None:
            sets.append("m.confidence = $confidence")
            params["confidence"] = confidence

        if not sets:
            return  # nothing to update

        sets.append("m.updated_at = datetime()")

        if self._use_db and self._driver:
            async with self._driver.session() as session:
                await session.run(
                    "MATCH (m:Memory {id: $id})"
                    f" SET {', '.join(sets)}",
                    **params,
                )
            return

        for memories in self._memories.values():
            for m in memories:
                if m["id"] == memory_id:
                    if content is not None:
                        m["content"] = content
                    if summary is not None:
                        m["summary"] = summary
                    if memory_type is not None:
                        m["memory_type"] = memory_type
                    if confidence is not None:
                        m["confidence"] = confidence
                    m["updated_at"] = now
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

    async def validate_memory(self, memory_id: str) -> None:
        """Increment validation_count and update validated_at timestamp."""
        self._init_driver()
        now = datetime.now(UTC)
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                await session.run(
                    """
                    MATCH (m:Memory {id: $id})
                    SET m.validation_count = coalesce(m.validation_count, 0) + 1,
                        m.validated_at = datetime(),
                        m.updated_at = datetime()
                    """,
                    id=memory_id,
                )
            return

        for memories in self._memories.values():
            for m in memories:
                if m["id"] == memory_id:
                    m["validation_count"] = (m.get("validation_count", 0) or 0) + 1
                    m["validated_at"] = now
                    m["updated_at"] = now
                    return

    async def mark_contradiction(self, memory_id: str, detected: bool = True) -> None:
        """Set the contradiction_detected flag on a memory."""
        self._init_driver()
        now = datetime.now(UTC)
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                await session.run(
                    """
                    MATCH (m:Memory {id: $id})
                    SET m.contradiction_detected = $detected,
                        m.updated_at = datetime()
                    """,
                    id=memory_id,
                    detected=detected,
                )
            return

        for memories in self._memories.values():
            for m in memories:
                if m["id"] == memory_id:
                    m["contradiction_detected"] = detected
                    m["updated_at"] = now
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

    async def create_update_relation(
        self,
        new_memory_id: str,
        old_memory_id: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Atomically mark old memory as replaced and create an UPDATES edge.

        AGENTS.md: 图谱操作必须是原子的。一个事实更新取代旧事实时，
        必须在单次事务中设置 is_latest=False 和创建 Update 关系。
        """
        self._init_driver()
        props = properties or {}
        now = datetime.now(UTC)

        if self._use_db and self._driver:
            async with self._driver.session() as session:
                await session.run(
                    """
                    MATCH (old:Memory {id: $old_id})
                    MATCH (new:Memory {id: $new_id})
                    WHERE old.is_latest = true
                    SET old.is_latest = false,
                        old.replaced_by = $new_id,
                        old.updated_at = datetime()
                    CREATE (new)-[r:UPDATES {
                        created_at: datetime(),
                        confidence: $confidence,
                        reason: $reason
                    }]->(old)
                    """,
                    old_id=old_memory_id,
                    new_id=new_memory_id,
                    confidence=props.get("confidence", 0.8),
                    reason=props.get("reason", ""),
                )
            return

        for memories in self._memories.values():
            for m in memories:
                if m["id"] == old_memory_id and m["is_latest"]:
                    m["is_latest"] = False
                    m["replaced_by"] = new_memory_id
                    m["updated_at"] = now
                    rels = m.setdefault("relationships", [])
                    rels.append({
                        "from_id": new_memory_id,
                        "type": "UPDATES",
                        "created_at": now,
                        **props,
                    })
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
                    f"""
                    MATCH (from:Memory {{id: $from_id}})
                    MATCH (to:Memory {{id: $to_id}})
                    CREATE (from)-[r:{rel_type.upper()}]->(to)
                    SET r.created_at = datetime()
                    SET r += $props
                    """,
                    from_id=from_id,
                    to_id=to_id,
                    props=props,
                )
            return

        # In-memory: store relationships on the target memory
        for memories in self._memories.values():
            for m in memories:
                if m["id"] == to_id:
                    rels = m.setdefault("relationships", [])
                    rels.append({
                        "from_id": from_id,
                        "to_id": to_id,
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

    async def get_relationship_by_property(
        self, rel_type: str, key: str, value: str
    ) -> dict[str, Any] | None:
        """Find a single relationship of ``rel_type`` with ``key=value``.

        Returns a dict with ``from_id``, ``to_id``, and the relationship
        properties, or ``None`` if not found.
        """
        self._init_driver()
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                result = await session.run(
                    f"""
                    MATCH (from:Memory)-[r:{rel_type.upper()}]->(to:Memory)
                    WHERE r.{key} = $value
                    RETURN from.id AS from_id, to.id AS to_id, r AS rel
                    LIMIT 1
                    """,
                    value=value,
                )
                record = await result.single()
                if record:
                    rel_props = dict(record["rel"])
                    rel_props["from_id"] = record["from_id"]
                    rel_props["to_id"] = record["to_id"]
                    return rel_props
                return None

        for memories in self._memories.values():
            for m in memories:
                for rel in m.get("relationships", []):
                    if rel.get("type") == rel_type and rel.get(key) == value:
                        return rel
        return None

    async def update_relationship_property(
        self,
        rel_type: str,
        from_id: str,
        to_id: str,
        key: str,
        value: Any,
    ) -> bool:
        """Update a property on a relationship identified by type and endpoints."""
        self._init_driver()
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                await session.run(
                    f"""
                    MATCH (from:Memory {{id: $from_id}})-[r:{rel_type.upper()}]
                          ->(to:Memory {{id: $to_id}})
                    SET r.{key} = $value
                    """,
                    from_id=from_id,
                    to_id=to_id,
                    value=value,
                )
                return True

        for memories in self._memories.values():
            for m in memories:
                if m.get("id") != to_id:
                    continue
                for rel in m.get("relationships", []):
                    if rel.get("type") == rel_type and rel.get("from_id") == from_id:
                        rel[key] = value
                        return True
        return False

    # ------------------------------------------------------------------
    # Space CRUD
    # ------------------------------------------------------------------

    async def create_space(
        self,
        container_tag: str,
        name: str,
        emoji: str,
        entity_id: str,
    ) -> dict[str, Any]:
        """Create a Space node linked to an Entity via [:HAS_SPACE].

        Uses MERGE for idempotency — calling twice with the same args
        will not create duplicates.

        Returns the space dict.
        """
        self._init_driver()
        now = datetime.now(UTC)

        if self._use_db and self._driver:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    MERGE (e:Entity {id: $entity_id})
                    ON CREATE SET e.created_at = datetime(), e.type = "user"
                    WITH e
                    MERGE (e)-[:HAS_SPACE]->(s:Space {
                        container_tag: $container_tag,
                        entity_id: $entity_id
                    })
                    ON CREATE SET
                        s.name = $name,
                        s.emoji = $emoji,
                        s.created_at = datetime(),
                        s.updated_at = datetime()
                    RETURN s.container_tag AS container_tag,
                           s.name AS name,
                           s.emoji AS emoji,
                           s.entity_id AS entity_id,
                           s.created_at AS created_at,
                           s.updated_at AS updated_at
                    """,
                    entity_id=entity_id,
                    container_tag=container_tag,
                    name=name,
                    emoji=emoji,
                )
                record = await result.single()
                if record:
                    return {
                        "container_tag": record["container_tag"],
                        "name": record["name"],
                        "emoji": record["emoji"],
                        "entity_id": record["entity_id"],
                        "created_at": record["created_at"],
                        "updated_at": record["updated_at"],
                    }
                # Fallback: build from inputs (should not normally reach here)
                return {
                    "container_tag": container_tag,
                    "name": name,
                    "emoji": emoji,
                    "entity_id": entity_id,
                    "created_at": now,
                    "updated_at": now,
                }

        # In-memory fallback
        key = f"space:{entity_id}"
        spaces = self._spaces.setdefault(key, [])
        for space in spaces:
            if space["container_tag"] == container_tag:
                return space
        space = {
            "container_tag": container_tag,
            "name": name,
            "emoji": emoji,
            "entity_id": entity_id,
            "created_at": now,
            "updated_at": now,
        }
        spaces.append(space)
        return space

    async def list_spaces(
        self,
        entity_id: str,
    ) -> list[dict[str, Any]]:
        """List all Spaces for an entity with memory_count.

        Uses OPTIONAL MATCH to count memories per space.
        Ordered: default first, then by name.
        """
        self._init_driver()
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    MATCH (e:Entity {id: $entity_id})-[:HAS_SPACE]->(s:Space)
                    OPTIONAL MATCH (m:Memory {
                        entity_id: $entity_id,
                        container_tag: s.container_tag
                    })
                    WITH s, count(m) AS memory_count
                    RETURN s.container_tag AS container_tag,
                           s.name AS name,
                           s.emoji AS emoji,
                           s.entity_id AS entity_id,
                           s.created_at AS created_at,
                           s.updated_at AS updated_at,
                           memory_count
                    ORDER BY
                      CASE WHEN s.container_tag = 'default' THEN 0 ELSE 1 END,
                      s.name
                    """,
                    entity_id=entity_id,
                )
                spaces = []
                async for record in result:
                    spaces.append({
                        "container_tag": record["container_tag"],
                        "name": record["name"],
                        "emoji": record["emoji"],
                        "entity_id": record["entity_id"],
                        "created_at": record["created_at"],
                        "updated_at": record["updated_at"],
                        "memory_count": record["memory_count"],
                    })
                return spaces

        # In-memory fallback
        key = f"space:{entity_id}"
        spaces = self._spaces.get(key, [])
        result = []
        for s in spaces:
            count = sum(
                1
                for m in self._memories.get(entity_id, [])
                if m.get("container_tag") == s["container_tag"]
            )
            result.append({**s, "memory_count": count})
        result.sort(key=lambda x: (0 if x["container_tag"] == "default" else 1, x.get("name", "")))
        return result

    async def update_space(
        self,
        container_tag: str,
        entity_id: str,
        name: str | None = None,
        emoji: str | None = None,
    ) -> dict[str, Any]:
        """Update Space name and/or emoji.

        Returns the updated space dict.
        """
        self._init_driver()
        now = datetime.now(UTC)

        if self._use_db and self._driver:
            sets = []
            params: dict[str, Any] = {
                "container_tag": container_tag,
                "entity_id": entity_id,
            }
            if name is not None:
                sets.append("s.name = $name")
                params["name"] = name
            if emoji is not None:
                sets.append("s.emoji = $emoji")
                params["emoji"] = emoji
            sets.append("s.updated_at = datetime()")

            async with self._driver.session() as session:
                await session.run(
                    f"""
                    MATCH (s:Space {{container_tag: $container_tag, entity_id: $entity_id}})
                    SET {', '.join(sets)}
                    """,
                    **params,
                )

            # Re-fetch to return updated state
            return await self.get_space(container_tag, entity_id)

        # In-memory fallback
        key = f"space:{entity_id}"
        spaces = self._spaces.get(key, [])
        for s in spaces:
            if s["container_tag"] == container_tag:
                if name is not None:
                    s["name"] = name
                if emoji is not None:
                    s["emoji"] = emoji
                s["updated_at"] = now
                return s
        return {
            "container_tag": container_tag,
            "entity_id": entity_id,
            "name": name,
            "emoji": emoji,
            "updated_at": now,
        }

    async def get_space(
        self,
        container_tag: str,
        entity_id: str,
    ) -> dict[str, Any]:
        """Get a single Space by container_tag + entity_id.

        Internal helper used by update_space to return updated state.
        """
        self._init_driver()
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    MATCH (s:Space {container_tag: $container_tag, entity_id: $entity_id})
                    RETURN s.container_tag AS container_tag,
                           s.name AS name,
                           s.emoji AS emoji,
                           s.entity_id AS entity_id,
                           s.created_at AS created_at,
                           s.updated_at AS updated_at
                    """,
                    container_tag=container_tag,
                    entity_id=entity_id,
                )
                record = await result.single()
                if record:
                    return {
                        "container_tag": record["container_tag"],
                        "name": record["name"],
                        "emoji": record["emoji"],
                        "entity_id": record["entity_id"],
                        "created_at": record["created_at"],
                        "updated_at": record["updated_at"],
                    }
                raise ValueError(
                    f"Space not found: container_tag={container_tag}, entity_id={entity_id}"
                )

        # In-memory fallback
        key = f"space:{entity_id}"
        spaces = self._spaces.get(key, [])
        for s in spaces:
            if s["container_tag"] == container_tag:
                return s
        raise ValueError(
            f"Space not found: container_tag={container_tag}, entity_id={entity_id}"
        )

    async def delete_space(
        self,
        container_tag: str,
        entity_id: str,
        migrate_to_default: bool = True,
    ) -> None:
        """Delete a Space node.

        If ``migrate_to_default`` is True (default), all memories with
        this container_tag are re-assigned to "default" first.
        """
        self._init_driver()
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                if migrate_to_default:
                    await session.run(
                        """
                        MATCH (m:Memory {entity_id: $entity_id, container_tag: $container_tag})
                        SET m.container_tag = 'default'
                        """,
                        entity_id=entity_id,
                        container_tag=container_tag,
                    )
                await session.run(
                    """
                    MATCH (s:Space {container_tag: $container_tag, entity_id: $entity_id})
                    DETACH DELETE s
                    """,
                    container_tag=container_tag,
                    entity_id=entity_id,
                )
            return

        # In-memory fallback
        key = f"space:{entity_id}"
        if migrate_to_default:
            for m in self._memories.get(entity_id, []):
                if m.get("container_tag") == container_tag:
                    m["container_tag"] = "default"
        spaces = self._spaces.get(key, [])
        self._spaces[key] = [
            s for s in spaces if s["container_tag"] != container_tag
        ]

    async def ensure_default_spaces(self) -> int:
        """Create a default Space for every Entity that doesn't have one.

        Returns the number of spaces created.
        """
        self._init_driver()
        now = datetime.now(UTC)

        if self._use_db and self._driver:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    MATCH (e:Entity)
                    WHERE NOT (e)-[:HAS_SPACE]->(:Space {container_tag: 'default'})
                    CREATE (s:Space {
                        container_tag: 'default',
                        name: 'My Space',
                        emoji: '📁',
                        entity_id: e.id,
                        created_at: datetime(),
                        updated_at: datetime()
                    })
                    CREATE (e)-[:HAS_SPACE]->(s)
                    RETURN count(s) AS created
                    """,
                )
                record = await result.single()
                return record["created"] if record else 0

        # In-memory fallback: iterate over all entities with memories
        created = 0
        for eid in list(self._memories.keys()):
            key = f"space:{eid}"
            spaces = self._spaces.get(key, [])
            if not any(s["container_tag"] == "default" for s in spaces):
                spaces.append({
                    "container_tag": "default",
                    "name": "My Space",
                    "emoji": "📁",
                    "entity_id": eid,
                    "created_at": now,
                    "updated_at": now,
                })
                self._spaces[key] = spaces
                created += 1
        return created
