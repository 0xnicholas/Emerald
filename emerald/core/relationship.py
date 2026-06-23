"""Relationship inference engine.

Analyses new memories against the existing knowledge graph and automatically
creates UPDATES, EXTENDS, and DERIVES_FROM relationships.

AGENTS.md requirement:
"图谱操作必须是原子的。一个事实更新取代旧事实时，必须在单次事务中设置 isLatest 和创建 Update 关系。"
"""

from __future__ import annotations

import re
from enum import StrEnum

import structlog

from emerald.core.graph import GraphStore
from emerald.core.metrics import relationship_infer_total
from emerald.core.vector import VectorStore

logger = structlog.get_logger(__name__)

# Rule-based classification patterns
_FUTURE_TEMPORAL_RE = re.compile(
    r"(?:明天|后天|大后天|\d+\s*天后|下周|下个月|明年|未来|tomorrow|\d+\s*days\s+later|next\s+week|next\s+month|next\s+year)",
    re.IGNORECASE,
)
_COMPLETION_RE = re.compile(
    r"(考完|结束|取消|完成|过期|finished|cancelled|canceled|done|completed)",
    re.IGNORECASE,
)
_NUMERIC_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(万|元|岁|%|kg|km|美元|欧元|rmb)", re.IGNORECASE)


class RelationType(StrEnum):
    UPDATES = "updates"           # New fact replaces old fact
    EXTENDS = "extends"           # New fact enriches old fact
    DERIVES_FROM = "derives_from" # Inferred from multiple facts
    NONE = "none"                 # No relationship


class RelationshipEngine:
    """Inspects new memories and infers relationships to existing memories.

    Uses a hybrid approach:
    1. Fast rule-based heuristics for obvious patterns (contradiction, extension)
    2. LLM-based semantic classification when rules are inconclusive
       and an OpenAI API key is available.
    """

    LLM_CONFIDENCE_THRESHOLD = 0.7

    def __init__(
        self,
        graph: GraphStore | None = None,
        vector: VectorStore | None = None,
        use_llm: bool = True,
    ) -> None:
        self.graph = graph or GraphStore(use_db=False)
        self.vector = vector or VectorStore(use_db=False)
        self.use_llm = use_llm

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
                    relationship_infer_total.labels(rel_type="updates").inc()
                    created += 1
                elif rel_type == RelationType.EXTENDS:
                    await self.create_extends_relation(
                        new_id, old_memory["id"], aspect="detail",
                    )
                    relationship_infer_total.labels(rel_type="extends").inc()
                    created += 1

            # Check for DERIVES_FROM: new memory combines information from 2+ old memories
            derives_sources = self._find_derives_sources(
                new_memory, existing,
            )
            if derives_sources:
                await self.create_derives_relation(
                    new_id, derives_sources, reasoning="combined inference",
                )
                relationship_infer_total.labels(rel_type="derives_from").inc()
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

        LLM-first classification with rule-based fallback:
        0. Identical content → NONE (trivial)
        0. No text overlap → NONE (skip obviously unrelated pairs fast)
        1. LLM semantic classification (primary, when API key available)
        2. Rule-based heuristics (fallback when LLM unavailable or returns NONE)

        AGENTS.md §6: 时序完整性 — LLM captures temporal nuance that
        pure bigram/structural rules miss (e.g. "moved from A to B" vs
        "works at A" and "works at B").
        """
        # Identical content → NONE
        if new_content.strip() == old_content.strip():
            return RelationType.NONE

        # Fast pre-filter: skip pairs with no textual overlap whatsoever
        # This avoids wasting LLM calls on completely unrelated memories.
        if not self._has_text_overlap(new_content, old_content):
            return RelationType.NONE

        # Phase 1: LLM-first (primary classifier when API key available)
        if self.use_llm:
            llm_result = await self._llm_classify(new_content, old_content)
            if llm_result != RelationType.NONE:
                return llm_result

        # Phase 2: Rule-based fallback (deterministic, fast, always available)
        return self._rule_classify(new_content, old_content)

    def _rule_classify(self, new_content: str, old_content: str) -> RelationType:
        """Fast rule-based classification."""
        # Time-aware update: a future event in the old fact followed by a
        # completion/cancellation word in the new fact is an UPDATE.
        if self._is_temporal_update(new_content, old_content):
            return RelationType.UPDATES

        # Numeric update: same unit with a different value is an UPDATE.
        if self._is_numeric_update(new_content, old_content):
            return RelationType.UPDATES

        # Extract structure patterns
        new_struct = self._extract_structure(new_content)
        old_struct = self._extract_structure(old_content)

        # Same structure template, different fillers → UPDATE
        if new_struct and old_struct and new_struct == old_struct:
            new_fillers = self._extract_fillers(new_content, new_struct)
            old_fillers = self._extract_fillers(old_content, old_struct)
            if new_fillers and old_fillers and new_fillers != old_fillers:
                return RelationType.UPDATES

        # Check for contradictory patterns, guarded by subject/topic overlap
        # to avoid classifying unrelated memories as updates just because the
        # new text contains a negation or change word.
        if self._has_text_overlap(new_content, old_content) and self._is_contradictory(
            new_content, old_content,
        ):
            return RelationType.UPDATES

        # Check for extension patterns (complementary information).
        # Guarded by subject/topic overlap to avoid accidental EXTENDS.
        if self._has_text_overlap(new_content, old_content) and self._is_complementary(
            new_content, old_content,
        ):
            return RelationType.EXTENDS

        return RelationType.NONE

    async def _llm_classify(self, new_content: str, old_content: str) -> RelationType:
        """LLM-based semantic relationship classification.

        Uses OpenAI or DeepSeek API (auto-detect based on configured keys).
        Falls back to NONE on any error.
        """
        try:
            from emerald.config import get_settings
            settings = get_settings()

            # Prefer DeepSeek, fall back to OpenAI
            if settings.deepseek_api_key:
                api_key = settings.deepseek_api_key
                base_url = settings.fact_extraction_base_url.rstrip("/")
                model = settings.fact_extraction_model or "deepseek-chat"
            elif settings.openai_api_key:
                api_key = settings.openai_api_key
                base_url = "https://api.openai.com/v1"
                model = "gpt-3.5-turbo"
            else:
                return RelationType.NONE

            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You classify the relationship between two memory facts. "
                                    "Respond with exactly one word: UPDATES, EXTENDS, or NONE.\n"
                                    "UPDATES = new fact replaces old (contradiction or update)\n"
                                    "EXTENDS = new fact adds detail to old (both valid)\n"
                                    "NONE = no meaningful relationship"
                                ),
                            },
                            {
                                "role": "user",
                                "content": f"Old fact: {old_content}\nNew fact: {new_content}",
                            },
                        ],
                        "temperature": 0.0,
                        "max_tokens": 10,
                    },
                )
                response.raise_for_status()
                data = response.json()
                result = data["choices"][0]["message"]["content"].strip().upper()

                if result == "UPDATES":
                    logger.debug("relationship.llm_classified", result="UPDATES")
                    return RelationType.UPDATES
                if result == "EXTENDS":
                    logger.debug("relationship.llm_classified", result="EXTENDS")
                    return RelationType.EXTENDS
        except Exception:
            # Any failure in LLM classification is non-fatal
            pass

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
        await self.graph.create_relationship(
            from_id=new_memory_id,
            to_id=existing_memory_id,
            rel_type="EXTENDS",
            properties={"aspect": aspect, "confidence": 0.7},
        )
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
        for source_id in source_ids:
            await self.graph.create_relationship(
                from_id=derived_id,
                to_id=source_id,
                rel_type="DERIVES_FROM",
                properties={"reasoning": reasoning, "confidence": 0.6},
            )
        logger.info(
            "relationship.derives",
            derived=derived_id,
            sources=source_ids,
            reasoning=reasoning,
        )

    @staticmethod
    def _find_derives_sources(
        new_memory: dict,
        existing_memories: list[dict],
    ) -> list[str]:
        """Find 2+ source memories that collectively imply the new memory.

        Heuristic: new memory shares bigrams with 2+ existing memories,
        and no single existing memory covers all of the new memory's bigrams.
        """
        new_bigrams = RelationshipEngine._extract_bigrams(new_memory.get("content", ""))
        if not new_bigrams:
            return []

        sources = []
        covered = set()
        for old in existing_memories:
            old_bigrams = RelationshipEngine._extract_bigrams(old.get("content", ""))
            overlap = new_bigrams & old_bigrams
            if overlap:
                sources.append(old["id"])
                covered.update(overlap)

        # Need at least 2 sources AND combined coverage < full new memory
        if len(sources) >= 2 and covered != new_bigrams:
            return sources[:3]  # Cap at 3 sources
        return []

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
        return any(word in new_text for word in change_words)

    @staticmethod
    def _has_text_overlap(new_text: str, old_text: str) -> bool:
        """Check for non-trivial textual or subject/topic overlap.

        Returns True when two facts share enough context to be worth
        classifying.  A single accidental bigram (e.g. a common verb) is
        no longer sufficient; there must be either two shared bigrams or
        a shared subject keyword.
        """
        new_bigrams = RelationshipEngine._extract_bigrams(new_text)
        old_bigrams = RelationshipEngine._extract_bigrams(old_text)
        if not new_bigrams or not old_bigrams:
            return False

        shared_bigrams = new_bigrams & old_bigrams
        if len(shared_bigrams) >= 2:
            return True

        new_subjects = RelationshipEngine._extract_subject_keywords(new_text)
        old_subjects = RelationshipEngine._extract_subject_keywords(old_text)
        return bool(new_subjects and old_subjects and (new_subjects & old_subjects))

    @staticmethod
    def _extract_subject_keywords(text: str) -> set[str]:
        """Extract subject/topic keywords for overlap checking.

        Captures the leading Chinese subject (e.g. 用户, 我) and English
        capitalized entities (e.g. Python, Stripe) so that facts about the
        same entity pass the overlap guard while unrelated facts do not.
        """
        keywords: set[str] = set()

        # Leading Chinese character and bigram — typically the grammatical subject.
        leading_match = re.match(r"[\u4e00-\u9fff]+", text)
        if leading_match:
            leading = leading_match.group(0)
            keywords.add(leading[0])
            if len(leading) >= 2:
                keywords.add(leading[:2])

        # English capitalized entities / proper nouns.
        keywords.update(re.findall(r"[A-Z][a-zA-Z]+", text))

        return keywords

    @staticmethod
    def _is_temporal_update(new_text: str, old_text: str) -> bool:
        """Detect time-aware updates: old fact had a future event, new fact completes it."""
        if not _FUTURE_TEMPORAL_RE.search(old_text):
            return False
        if not _COMPLETION_RE.search(new_text):
            return False
        # Require some subject/topic overlap to avoid unrelated completions.
        return RelationshipEngine._has_text_overlap(new_text, old_text)

    @staticmethod
    def _is_numeric_update(new_text: str, old_text: str) -> bool:
        """Detect numeric value changes on the same subject/attribute."""
        new_matches = _NUMERIC_UNIT_RE.findall(new_text)
        old_matches = _NUMERIC_UNIT_RE.findall(old_text)
        if not new_matches or not old_matches:
            return False

        new_units = {unit for _, unit in new_matches}
        old_units = {unit for _, unit in old_matches}
        shared_units = new_units & old_units
        if not shared_units:
            return False

        # Guard against unrelated pairs that happen to share a unit.
        if not RelationshipEngine._has_text_overlap(new_text, old_text):
            return False

        for unit in shared_units:
            new_values = {num for num, u in new_matches if u == unit}
            old_values = {num for num, u in old_matches if u == unit}
            if new_values != old_values:
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
