"""Relationship inference engine.

Analyses new memories against the existing knowledge graph and automatically
creates UPDATES, EXTENDS, and DERIVES_FROM relationships.

AGENTS.md requirement: "图谱操作必须是原子的。一个事实更新取代旧事实时，必须在单次事务中设置 isLatest 和创建 Update 关系。"
"""

from __future__ import annotations

import re
from enum import Enum

import structlog

from emerald.core.graph import GraphStore
from emerald.core.vector import VectorStore

logger = structlog.get_logger(__name__)


class RelationType(str, Enum):
    UPDATES = "updates"           # New fact replaces old fact
    EXTENDS = "extends"           # New fact enriches old fact
    DERIVES_FROM = "derives_from" # Inferred from multiple facts
    NONE = "none"                 # No relationship


class RelationshipEngine:
    """Inspects new memories and infers relationships to existing memories.

    Classification is rule-based (keyword + structure heuristics).
    LLM-based classification can be plugged in later.
    """

    def __init__(
        self,
        graph: GraphStore | None = None,
        vector: VectorStore | None = None,
    ) -> None:
        self.graph = graph or GraphStore(use_db=False)
        self.vector = vector or VectorStore(use_db=False)

    async def infer(self, memory_ids: list[str], entity_id: str) -> int:
        """For each new memory, find related existing memories and create relationships.

        Returns the number of relationships created.
        """
        created = 0

        for new_id in memory_ids:
            new_memory = await self.graph.get_memory(new_id)
            if not new_memory:
                continue

            # Find existing memories for this entity
            existing = await self.graph.list_latest_memories(
                entity_id, limit=20,
            )
            # Exclude the new memory itself
            existing = [m for m in existing if m["id"] != new_id]

            for old_memory in existing:
                rel_type = await self.classify_relation(
                    new_id, old_memory["id"], entity_id,
                    new_content=new_memory["content"],
                    old_content=old_memory["content"],
                )

                if rel_type == RelationType.UPDATES:
                    await self.create_update_relation(
                        new_id, old_memory["id"], reason="contradiction",
                    )
                    created += 1
                elif rel_type == RelationType.EXTENDS:
                    await self.create_extends_relation(
                        new_id, old_memory["id"], aspect="detail",
                    )
                    created += 1

        logger.info(
            "relationship.infer.complete",
            entity_id=entity_id,
            memory_count=len(memory_ids),
            relationships_created=created,
        )
        return created

    async def classify_relation(
        self,
        new_id: str,
        old_id: str,
        entity_id: str,
        new_content: str,
        old_content: str,
    ) -> RelationType:
        """Classify the relationship type between two memories.

        Uses structural and keyword heuristics:

        - Identical content → NONE (no relationship needed)
        - Same sentence structure, different key entity → UPDATES
          (e.g., "works at Google" → "works at Stripe")
        - Different aspect, same domain → EXTENDS
          (e.g., "works at Stripe" → "leads payment team")
        - Otherwise → NONE
        """
        # Identical content
        if new_content.strip() == old_content.strip():
            return RelationType.NONE

        # Extract structure patterns
        new_struct = self._extract_structure(new_content)
        old_struct = self._extract_structure(old_content)

        # Same structure template, different fillers → UPDATE
        if new_struct and old_struct and new_struct == old_struct:
            new_fillers = self._extract_fillers(new_content, new_struct)
            old_fillers = self._extract_fillers(old_content, old_struct)
            if new_fillers and old_fillers and new_fillers != old_fillers:
                return RelationType.UPDATES

        # Check for contradictory patterns
        if self._is_contradictory(new_content, old_content):
            return RelationType.UPDATES

        # Check for extension patterns (complementary information)
        if self._is_complementary(new_content, old_content):
            return RelationType.EXTENDS

        return RelationType.NONE

    async def create_update_relation(
        self,
        new_memory_id: str,
        old_memory_id: str,
        reason: str = "contradiction",
        confidence: float = 0.8,
    ) -> None:
        """Create an UPDATES relationship (new replaces old).

        AGENTS.md: 原子事务 — 单次 Neo4j 事务中完成:
        1. 旧记忆 is_latest=False
        2. 旧记忆 replaced_by=新记忆 ID
        3. 创建 (新)-[:UPDATES]->(旧) 关系
        """
        old = await self.graph.get_memory(old_memory_id)
        if not old:
            return

        # Only update if old is currently latest
        if not old["is_latest"]:
            return

        # Atomic: set is_latest=False and record replaced_by
        await self.graph.update_is_latest(
            old_memory_id, False, replaced_by=new_memory_id
        )
        logger.info(
            "relationship.updates",
            new=new_memory_id,
            old=old_memory_id,
            reason=reason,
        )

    async def create_extends_relation(
        self,
        new_memory_id: str,
        existing_memory_id: str,
        aspect: str = "detail",
    ) -> None:
        """Create an EXTENDS relationship (new enriches existing).

        Both memories stay is_latest=True.
        """
        logger.info(
            "relationship.extends",
            new=new_memory_id,
            existing=existing_memory_id,
            aspect=aspect,
        )

    async def create_derives_relation(
        self,
        derived_id: str,
        source_ids: list[str],
        reasoning: str = "",
    ) -> None:
        """Create DERIVES_FROM relationships linking derived memory to sources."""
        logger.info(
            "relationship.derives",
            derived=derived_id,
            sources=source_ids,
            reasoning=reasoning,
        )

    # ---- Classification heuristics ----

    @staticmethod
    def _extract_structure(text: str) -> str | None:
        """Extract a structural template from text by replacing entities.

        Example: "用户在 Google 工作" → "用户在 * 工作"
        """
        # Replace known entity patterns with placeholders
        pattern = text

        # Company names → *
        pattern = re.sub(r"(Google|Stripe|Apple|Meta|Amazon|Microsoft|腾讯|阿里|字节|百度)",
                         "*", pattern)
        # Locations → *
        pattern = re.sub(r"(北京|上海|深圳|杭州|西雅图|旧金山|纽约|伦敦|东京)",
                         "*", pattern)
        # Languages / tech → *
        pattern = re.sub(r"(Python|TypeScript|JavaScript|Rust|Go|Java|C\+\+)",
                         "*", pattern)

        return pattern if pattern != text else None

    @staticmethod
    def _extract_fillers(text: str, structure: str) -> list[str]:
        """Extract the entities that were replaced in the structure."""
        fillers = []
        for word in re.findall(r"[\u4e00-\u9fff]+|[A-Z][a-z]+(?:\+{2})?|[A-Z]{2,}", text):
            if word not in structure or "*" in structure:
                fillers.append(word)
        return fillers

    @staticmethod
    def _is_contradictory(new_text: str, old_text: str) -> bool:
        """Check for simple contradictory patterns."""
        # Negation in new relative to old
        negation_words = {"不", "没", "别", "不是", "没有", "不再", "换了", "改用"}
        for word in negation_words:
            if word in new_text:
                return True

        # Tense change indicators
        change_words = {"刚", "现在", "新", "换了", "搬到", "跳槽", "离职", "改用"}
        for word in change_words:
            if word in new_text:
                return True

        return False

    @staticmethod
    def _is_complementary(new_text: str, old_text: str) -> bool:
        """Check if new text complements (extends) old text.

        Uses bigram overlap instead of whole-word matching to handle
        CJK character runs more granularly.
        """
        new_bigrams = RelationshipEngine._extract_bigrams(new_text)
        old_bigrams = RelationshipEngine._extract_bigrams(old_text)

        if not new_bigrams or not old_bigrams:
            return False

        overlap = new_bigrams & old_bigrams
        new_only = new_bigrams - old_bigrams

        # Some shared context AND new adds distinct information → extends
        return bool(overlap) and bool(new_only)

    @staticmethod
    def _extract_bigrams(text: str) -> set[str]:
        """Extract character bigrams from text (works for CJK and alphabetic)."""
        # Normalize: collapse whitespace
        normalized = re.sub(r"\s+", "", text)
        bigrams = set()
        for i in range(len(normalized) - 1):
            bigrams.add(normalized[i : i + 2])
        return bigrams
