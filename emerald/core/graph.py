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

from emerald.core.mentions import (
    MENTION_CONFIDENCE_THRESHOLD,
    Mention,
    coerce_confidence,
    normalize_mention_type,
)

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
        # In-memory store: entity_id → list of Mention node dicts (B3 NER)
        self._mentions: dict[str, list[dict[str, Any]]] = {}

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
        container_tag: str | None = None,
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
        tags: list[str] | None = None,
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
                        tags: $tags,
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
                    tags=tags or [],
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
                "tags": tags or [],
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

    async def update_memory_tags(
        self,
        memory_id: str,
        tags: list[str],
    ) -> None:
        """Replace the tags on a memory."""
        self._init_driver()
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                await session.run(
                    """
                    MATCH (m:Memory {id: $id})
                    SET m.tags = $tags, m.updated_at = datetime()
                    """,
                    id=memory_id,
                    tags=tags,
                )
            return

        for memories in self._memories.values():
            for m in memories:
                if m["id"] == memory_id:
                    m["tags"] = tags
                    m["updated_at"] = datetime.now(UTC)
                    return

    async def update_memory(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        summary: str | None = None,
        memory_type: str | None = None,
        confidence: float | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Update a memory's content, summary, type, confidence, and/or tags."""
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
        if tags is not None:
            sets.append("m.tags = $tags")
            params["tags"] = tags

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
                    if tags is not None:
                        m["tags"] = tags
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

        Forgetting integration (B3 NER, #27): forgetting also removes the
        memory's MENTIONS edges and prunes Mention nodes left with zero
        remaining MENTIONS edges, so the graph never accumulates dead
        mention nodes. Every ForgetEngine strategy funnels through this
        seam (spec #21: 扩展现有遗忘路径).

        The UPDATES replacement path goes through ``update_is_latest``
        instead — a replaced memory is a historical node and keeps its
        MENTIONS edges (#26).
        """
        self._init_driver()
        now = datetime.now(UTC)
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                # One statement = one transaction (AGENTS.md: 图谱操作
                # 必须是原子的): expiry, edge removal, count decrement
                # and orphan pruning commit or roll back together.
                await session.run(
                    """
                    MATCH (m:Memory {id: $id})
                    SET m.is_latest = false,
                        m.expired_at = datetime(),
                        m.replaced_by = $reason,
                        m.updated_at = datetime()
                    WITH m
                    OPTIONAL MATCH (m)-[r:MENTIONS]->(mn:Mention)
                    WITH mn, count(r) AS removed
                    SET mn.mention_count = CASE
                        WHEN coalesce(mn.mention_count, 0) <= removed THEN 0
                        ELSE coalesce(mn.mention_count, 0) - removed
                    END
                    WITH mn
                    MATCH (m:Memory {id: $id})-[r:MENTIONS]->(mn)
                    DELETE r
                    WITH DISTINCT mn
                    WHERE NOT ()-[:MENTIONS]->(mn)
                    DETACH DELETE mn
                    """,
                    id=memory_id,
                    reason=reason,
                )
            return

        for entity_id, memories in self._memories.items():
            for m in memories:
                if m["id"] == memory_id:
                    m["is_latest"] = False
                    m["expired_at"] = now
                    m["replaced_by"] = reason
                    m["updated_at"] = now
                    if m.pop("mentions", []):
                        self._prune_orphaned_mentions(entity_id, memories)
                    return

    def _prune_orphaned_mentions(
        self,
        entity_id: str,
        memories: list[dict[str, Any]],
    ) -> None:
        """Prune Mention nodes left with zero live MENTIONS edges (#27).

        In-memory mirror of the Cypher prune in ``mark_expired``. Called
        after a forgotten memory's edges are removed: surviving nodes keep
        their aliases and last_seen_at (surface forms ever seen, including
        the forgotten memory's), while mention_count is recomputed as the
        number of remaining live edges into the node.
        """
        pool = self._mentions.get(entity_id, [])
        if not pool:
            return
        live_counts: dict[str, int] = {}
        for memory in memories:
            for edge in memory.get("mentions", []):
                mention_id = edge["mention_id"]
                live_counts[mention_id] = live_counts.get(mention_id, 0) + 1
        surviving = []
        for node in pool:
            count = live_counts.get(node["id"], 0)
            if count == 0:
                continue  # orphan — prune the dead node
            node["mention_count"] = count
            surviving.append(node)
        self._mentions[entity_id] = surviving

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

        # Parity with the Cypher branch: the source (new) memory must exist,
        # otherwise the operation is a no-op (no phantom archiving).
        new_exists = any(
            m["id"] == new_memory_id
            for memories in self._memories.values()
            for m in memories
        )
        if not new_exists:
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

    async def get_relationship_neighbors(
        self,
        memory_ids: list[str],
        rel_types: list[str] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Adjacent memories via relationship edges, both directions (B4, #32).

        Returns ``{memory_id: [{id, rel_type, direction, entity_id,
        is_latest}]}`` — one entry per adjacent edge of the keyed memory.
        ``direction`` is ``"out"`` (keyed → neighbor) or ``"in"``
        (neighbor → keyed). Historical neighbors (is_latest=False) are
        included; the walker decides terminality (spec #29: history only
        surfaces along UPDATES chains and is never walked through).
        """
        if rel_types is None:
            rel_types = ["UPDATES", "EXTENDS", "DERIVES_FROM"]

        self._init_driver()
        id_set = set(memory_ids)
        result: dict[str, list[dict[str, Any]]] = {}
        if not id_set:
            return result

        if self._use_db and self._driver:
            async with self._driver.session() as session:
                res = await session.run(
                    """
                    MATCH (m:Memory)-[r]->(other:Memory)
                    WHERE m.id IN $ids AND type(r) IN $rel_types
                    RETURN m.id AS mid, other.id AS oid, type(r) AS rel_type,
                           "out" AS direction, other.entity_id AS entity_id,
                           other.is_latest AS is_latest
                    UNION
                    MATCH (other:Memory)-[r]->(m:Memory)
                    WHERE m.id IN $ids AND type(r) IN $rel_types
                    RETURN m.id AS mid, other.id AS oid, type(r) AS rel_type,
                           "in" AS direction, other.entity_id AS entity_id,
                           other.is_latest AS is_latest
                    """,
                    ids=list(id_set),
                    rel_types=rel_types,
                )
                async for record in res:
                    result.setdefault(record["mid"], []).append(
                        {
                            "id": record["oid"],
                            "rel_type": record["rel_type"],
                            "direction": record["direction"],
                            "entity_id": record["entity_id"],
                            "is_latest": record["is_latest"],
                        }
                    )
            return result

        # In-memory fallback. Every relationship record is stored on its
        # target memory (create_relationship / create_update_relation), so
        # the holder's id IS the edge target.
        by_id: dict[str, dict[str, Any]] = {}
        for entity_memories in self._memories.values():
            for m in entity_memories:
                by_id[m["id"]] = m
        for m in by_id.values():
            for rel in m.get("relationships", []):
                if rel["type"] not in rel_types:
                    continue
                from_id = rel["from_id"]
                to_id = m["id"]
                if to_id in id_set:
                    source = by_id.get(from_id)
                    if source is not None:
                        result.setdefault(to_id, []).append(
                            {
                                "id": from_id,
                                "rel_type": rel["type"],
                                "direction": "in",
                                "entity_id": source.get("entity_id"),
                                "is_latest": source.get("is_latest", True),
                            }
                        )
                if from_id in id_set:
                    result.setdefault(from_id, []).append(
                        {
                            "id": to_id,
                            "rel_type": rel["type"],
                            "direction": "out",
                            "entity_id": m.get("entity_id"),
                            "is_latest": m.get("is_latest", True),
                        }
                    )
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
    # Mention nodes (B3 NER) — internal methods only, no public API (#22)
    # ------------------------------------------------------------------

    async def attach_mentions(
        self,
        memory_id: str,
        entity_id: str,
        mentions: list[Mention],
    ) -> int:
        """Attach Mention nodes to a memory (B3 NER, tickets #22/#23).

        For each mention ensures, within the entity's context pool:

            (:Entity)-[:HAS_MENTION]->(:Mention)
            (:Memory)-[:MENTIONS]->(:Mention)

        Mention nodes carry id, entity_id, canonical_form, type, aliases,
        mention_count, created_at and last_seen_at; MENTIONS edges carry
        surface_form and confidence (direction Memory → Mention).

        Cross-memory resolution (#23): the dedup key is
        (entity_id, canonical_form, type) — different surface forms of the
        same real-world thing (e.g. "Google" / "谷歌") resolve to one shared
        Mention node. Newly seen surface forms accumulate into the node's
        aliases; mention_count counts the MENTIONS edges into the node.
        Repeated creation is idempotent: re-attaching the same memory's
        mention neither duplicates the node nor the edge, nor inflates the
        count.

        Best-effort: mentions with an empty surface/canonical form are
        skipped and a missing memory is a no-op — extraction must never
        fail ingestion. Closed taxonomy (#24): a type outside the taxonomy
        falls back to ``concept``; a mention below the confidence threshold
        is dropped (no node, no edge). Returns the number of new MENTIONS
        edges attached.
        """
        self._init_driver()
        # A missing memory is a no-op on both backends: the Cypher MATCH
        # silently produces no rows, so the existence check happens here
        # to keep the return value honest (0 = nothing attached).
        if await self.get_memory(memory_id) is None:
            return 0

        now = datetime.now(UTC)

        prepared: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for mention in mentions:
            data = mention.to_dict()
            surface = str(data.get("surface_form", "")).strip()
            canonical = str(data.get("canonical_form", "")).strip()
            if not surface or not canonical:
                continue
            mention_type = normalize_mention_type(
                str(data.get("type", "concept"))
            )
            confidence = coerce_confidence(data.get("confidence"))
            # Confidence gating (#24): below-threshold mentions are dropped
            # — they must produce no Mention node and no MENTIONS edge.
            if confidence < MENTION_CONFIDENCE_THRESHOLD:
                continue
            # The identical mention twice in one call attaches once (#23).
            key = (surface, canonical, mention_type)
            if key in seen:
                continue
            seen.add(key)
            prepared.append(
                {
                    "id": uuid4().hex,
                    "surface_form": surface,
                    "canonical_form": canonical,
                    "type": mention_type,
                    "confidence": confidence,
                }
            )

        if not prepared:
            return 0

        if self._use_db and self._driver:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    MATCH (m:Memory {id: $memory_id})
                    MATCH (e:Entity {id: $entity_id})
                    UNWIND $mentions AS mention
                    MERGE (mn:Mention {
                        entity_id: $entity_id,
                        canonical_form: mention.canonical_form,
                        type: mention.type
                    })
                    ON CREATE SET
                        mn.id = mention.id,
                        mn.aliases = [mention.surface_form],
                        // Starts at 0: the guarded SET below counts this
                        // first edge, mirroring the in-memory branch's
                        // mention_count=1 at node creation.
                        mn.mention_count = 0,
                        mn.created_at = datetime(),
                        mn.last_seen_at = datetime()
                    MERGE (e)-[:HAS_MENTION]->(mn)
                    WITH m, mn, mention
                    OPTIONAL MATCH (m)-[existing:MENTIONS
                        {surface_form: mention.surface_form}]->(mn)
                    WITH m, mn, mention, existing
                    FOREACH (_ IN CASE WHEN existing IS NULL THEN [1] ELSE [] END |
                        CREATE (m)-[:MENTIONS {
                            surface_form: mention.surface_form,
                            confidence: mention.confidence,
                            created_at: datetime()
                        }]->(mn)
                        SET mn.mention_count = mn.mention_count + 1,
                            mn.aliases = CASE
                                WHEN mention.surface_form IN mn.aliases
                                THEN mn.aliases
                                ELSE mn.aliases + mention.surface_form
                            END,
                            mn.last_seen_at = datetime()
                    )
                    RETURN count(existing) AS preexisting
                    """,
                    memory_id=memory_id,
                    entity_id=entity_id,
                    mentions=prepared,
                )
                record = await result.single()
                # No rows: the memory or entity node is missing — nothing
                # was attached (parity with the no-op above).
                attached = (
                    0
                    if record is None
                    else len(prepared) - int(record["preexisting"])
                )
        else:
            target = None
            for memories in self._memories.values():
                for memory in memories:
                    if memory["id"] == memory_id:
                        target = memory
                        break
                if target is not None:
                    break
            if target is None:
                return 0  # defensive parity with the existence check above

            pool = self._mentions.setdefault(entity_id, [])
            edges = target.setdefault("mentions", [])
            attached = 0
            for mention_dict in prepared:
                surface = mention_dict["surface_form"]
                node = next(
                    (
                        n
                        for n in pool
                        if n["canonical_form"] == mention_dict["canonical_form"]
                        and n["type"] == mention_dict["type"]
                    ),
                    None,
                )
                if node is None:
                    # First mention of this thing in the pool: the node
                    # starts with this edge (count 1) and this alias.
                    node = {
                        "id": mention_dict["id"],
                        "entity_id": entity_id,
                        "canonical_form": mention_dict["canonical_form"],
                        "type": mention_dict["type"],
                        "aliases": [surface],
                        "mention_count": 1,
                        "created_at": now,
                        "last_seen_at": now,
                    }
                    pool.append(node)
                else:
                    # Idempotency: this memory already carries an edge to
                    # this node with this surface form — change nothing.
                    if any(
                        edge["mention_id"] == node["id"] and edge["surface_form"] == surface
                        for edge in edges
                    ):
                        continue
                    if surface not in node["aliases"]:
                        node["aliases"].append(surface)
                    node["mention_count"] += 1
                    node["last_seen_at"] = now
                edges.append(
                    {
                        "mention_id": node["id"],
                        "surface_form": surface,
                        "confidence": mention_dict["confidence"],
                        "created_at": now,
                    }
                )
                attached += 1

        logger.info(
            "graph.mentions.attached",
            memory_id=memory_id,
            entity_id=entity_id,
            count=attached,
        )
        return attached

    async def get_memory_mentions(self, memory_id: str) -> list[dict[str, Any]]:
        """Read back the mentions of a memory (B3 NER internal method).

        Returns one dict per MENTIONS edge (Memory → Mention), merging the
        Mention node fields with the edge's surface_form/confidence:

        {id, entity_id, canonical_form, type, aliases, mention_count,
         surface_form, confidence}

        Empty list when the memory has no mentions or does not exist.
        """
        self._init_driver()
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    MATCH (m:Memory {id: $id})-[r:MENTIONS]->(mn:Mention)
                    RETURN mn.id AS id,
                           mn.entity_id AS entity_id,
                           mn.canonical_form AS canonical_form,
                           mn.type AS type,
                           mn.aliases AS aliases,
                           mn.mention_count AS mention_count,
                           r.surface_form AS surface_form,
                           r.confidence AS confidence
                    """,
                    id=memory_id,
                )
                mentions = []
                async for record in result:
                    mentions.append({
                        "id": record["id"],
                        "entity_id": record["entity_id"],
                        "canonical_form": record["canonical_form"],
                        "type": record["type"],
                        "aliases": record["aliases"],
                        "mention_count": record["mention_count"],
                        "surface_form": record["surface_form"],
                        "confidence": record["confidence"],
                    })
                return mentions

        for memories in self._memories.values():
            for memory in memories:
                if memory["id"] != memory_id:
                    continue
                pool: list[dict[str, Any]] = self._mentions.get(
                    memory.get("entity_id", ""), []
                )
                by_id = {n["id"]: n for n in pool}
                mentions = []
                for edge in memory.get("mentions", []):
                    node = by_id.get(edge["mention_id"])
                    if node is None:
                        continue
                    mentions.append({
                        "id": node["id"],
                        "entity_id": node["entity_id"],
                        "canonical_form": node["canonical_form"],
                        "type": node["type"],
                        "aliases": node["aliases"],
                        "mention_count": node["mention_count"],
                        "surface_form": edge["surface_form"],
                        "confidence": edge["confidence"],
                    })
                return mentions
        return []

    async def get_memories_mentioning(
        self,
        entity_id: str,
        about: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List an entity's latest memories mentioning a named thing (B4, #30).

        ``about`` is a mention canonical form or a Mention node id. The
        match is entity-scoped and type-independent for canonical forms:
        every Mention node in the entity whose canonical_form equals
        ``about`` contributes its referencing memories — surface forms are
        irrelevant (resolution is the B3 dedup semantics). A node-id match
        is exact (type participates).

        Historical memories (is_latest=false) are excluded: plain
        entity-centric retrieval does not reach into history (spec #29:
        不主动搜历史 — UPDATES chains come in #32). Returns one dict per
        memory, newest first, empty list when nothing matches.
        """
        self._init_driver()
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    MATCH (mn:Mention {entity_id: $entity_id})
                    WHERE mn.canonical_form = $about OR mn.id = $about
                    MATCH (mn)<-[:MENTIONS]-(m:Memory)
                    WHERE m.is_latest = true
                      AND m.entity_id = $entity_id
                    RETURN DISTINCT m
                    ORDER BY m.created_at DESC
                    LIMIT $limit
                    """,
                    entity_id=entity_id,
                    about=about,
                    limit=limit,
                )
                memories = []
                async for record in result:
                    memories.append(dict(record["m"]))
                return memories

        pool: list[dict[str, Any]] = self._mentions.get(entity_id, [])
        matching_nodes = {
            n["id"]
            for n in pool
            if n["canonical_form"] == about or n["id"] == about
        }
        if not matching_nodes:
            return []
        memories = []
        for m in self._memories.get(entity_id, []):
            if not m["is_latest"]:
                continue
            if any(
                edge["mention_id"] in matching_nodes
                for edge in m.get("mentions", [])
            ):
                memories.append(m)
        memories.sort(
            key=lambda m: m.get("created_at", datetime.min.replace(tzinfo=UTC)),
            reverse=True,
        )
        return memories[:limit]

    async def get_entity_mentions(self, entity_id: str) -> list[dict[str, Any]]:
        """Read back an entity's resolved Mention nodes (B3 NER, #25).

        Internal quality-suite method (spec #21: no public API in B3).
        Returns one dict per Mention node in the entity's context pool:

        {id, entity_id, canonical_form, type, aliases, mention_count,
         created_at, last_seen_at}

        Empty list when the entity has no mentions or does not exist.
        """
        self._init_driver()
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    MATCH (e:Entity {id: $id})-[:HAS_MENTION]->(mn:Mention)
                    RETURN mn.id AS id,
                           mn.entity_id AS entity_id,
                           mn.canonical_form AS canonical_form,
                           mn.type AS type,
                           mn.aliases AS aliases,
                           mn.mention_count AS mention_count,
                           mn.created_at AS created_at,
                           mn.last_seen_at AS last_seen_at
                    ORDER BY mn.created_at
                    """,
                    id=entity_id,
                )
                mentions = []
                async for record in result:
                    mentions.append({
                        "id": record["id"],
                        "entity_id": record["entity_id"],
                        "canonical_form": record["canonical_form"],
                        "type": record["type"],
                        "aliases": list(record["aliases"]),
                        "mention_count": record["mention_count"],
                        "created_at": record["created_at"],
                        "last_seen_at": record["last_seen_at"],
                    })
                return mentions

        pool: list[dict[str, Any]] = self._mentions.get(entity_id, [])
        return [
            {
                "id": node["id"],
                "entity_id": node["entity_id"],
                "canonical_form": node["canonical_form"],
                "type": node["type"],
                "aliases": list(node["aliases"]),
                "mention_count": node["mention_count"],
                "created_at": node["created_at"],
                "last_seen_at": node["last_seen_at"],
            }
            for node in pool
        ]

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
        result.sort(key=lambda x: x.get("name", ""))
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
        detach_memories: bool = True,
    ) -> None:
        """Delete a Space node.

        If ``detach_memories`` is True (default), all memories with this
        container_tag lose their space (container_tag becomes null).
        """
        self._init_driver()
        if self._use_db and self._driver:
            async with self._driver.session() as session:
                if detach_memories:
                    await session.run(
                        """
                        MATCH (m:Memory {entity_id: $entity_id, container_tag: $container_tag})
                        REMOVE m.container_tag
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
        if detach_memories:
            for m in self._memories.get(entity_id, []):
                if m.get("container_tag") == container_tag:
                    m["container_tag"] = None
        spaces = self._spaces.get(key, [])
        self._spaces[key] = [
            s for s in spaces if s["container_tag"] != container_tag
        ]
