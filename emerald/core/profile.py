"""Profile manager — entity profile maintenance.

Maintains a two-tier profile for each entity:
- static facts (fact/preference type, high confidence, always relevant)
- dynamic facts (recent episodic, contextual)

AGENTS.md:
- "画像在摄入后增量更新。只在新增记忆可能影响画像时才重新计算。"
- "画像必须快速。静态 + 动态画像接口必须在 100ms 内返回。"
- "缓存 TTL 默认 24h，摄入新内容时主动失效"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import structlog

from emerald.core.graph import GraphStore

logger = structlog.get_logger(__name__)


@dataclass
class ProfileFact:
    content: str
    importance: float = 1.0
    relevance: float = 1.0
    source: str = ""
    acquired_at: str = ""


@dataclass
class EntityProfile:
    entity_id: str
    static: list[ProfileFact] = field(default_factory=list)
    dynamic: list[ProfileFact] = field(default_factory=list)
    memory_count: int = 0
    computed_at: str = ""
    version: int = 1


class ProfileManager:
    """Manages entity profiles: compute, cache, invalidate.

    Uses in-memory cache (dict) for testing. In production, substitutes
    with Redis via the same interface.
    """

    # Thresholds
    STATIC_CONFIDENCE_MIN = 0.5
    DYNAMIC_CONFIDENCE_MIN = 0.3
    DYNAMIC_LOOKBACK_DAYS = 7
    STATIC_MAX_ITEMS = 10
    DYNAMIC_MAX_ITEMS = 5

    def __init__(
        self,
        graph: GraphStore | None = None,
        cache: dict | None = None,
    ) -> None:
        self.graph = graph or GraphStore(use_db=False)
        self._cache: dict[str, EntityProfile] = cache or {}
        self._versions: dict[str, int] = {}  # Survives invalidation

    async def get(self, entity_id: str) -> EntityProfile:
        """Get entity profile. Checks cache first, computes on miss.

        Target: ~50ms when cached.
        """
        # Cache hit
        if entity_id in self._cache:
            logger.debug("profile.cache.hit", entity_id=entity_id)
            return self._cache[entity_id]

        # Cache miss — compute from graph
        logger.info("profile.cache.miss", entity_id=entity_id)
        profile = await self.compute(entity_id)

        # Store in cache
        self._cache[entity_id] = profile
        return profile

    async def invalidate(self, entity_id: str) -> None:
        """Invalidate profile cache after new memories are ingested.

        Called at the end of the pipeline INDEXING stage.
        """
        if entity_id in self._cache:
            del self._cache[entity_id]
            logger.info("profile.cache.invalidated", entity_id=entity_id)

    async def compute(self, entity_id: str) -> EntityProfile:
        """Compute profile from the graph store.

        Static facts: fact/preference type, confidence >= 0.5, is_latest=True
        Dynamic facts: episodic type, created within 7 days, confidence >= 0.3
        """
        all_memories = await self.graph.list_latest_memories(entity_id, limit=200)
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=self.DYNAMIC_LOOKBACK_DAYS)

        static_facts: list[ProfileFact] = []
        dynamic_facts: list[ProfileFact] = []

        for m in all_memories:
            memory_type = m.get("memory_type", "fact")
            confidence = m.get("confidence", 0.5)
            created_at = m.get("created_at", now)
            content = m.get("content", "")

            # Static: fact or preference with high confidence
            if memory_type in ("fact", "preference") and confidence >= self.STATIC_CONFIDENCE_MIN:
                static_facts.append(
                    ProfileFact(
                        content=content,
                        importance=confidence,
                        acquired_at=created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
                    )
                )

            # Dynamic: episodic and recent
            if memory_type == "episodic" and confidence >= self.DYNAMIC_CONFIDENCE_MIN:
                if hasattr(created_at, "isoformat"):
                    if created_at >= cutoff:
                        dynamic_facts.append(
                            ProfileFact(
                                content=content,
                                relevance=confidence,
                                source="最近对话",
                                acquired_at=created_at.isoformat(),
                            )
                        )
                else:
                    # Timestamp parsing fallback
                    dynamic_facts.append(
                        ProfileFact(
                            content=content,
                            relevance=confidence,
                            source="最近对话",
                        )
                    )

        # Sort by importance/relevance descending
        static_facts.sort(key=lambda f: f.importance, reverse=True)
        dynamic_facts.sort(key=lambda f: f.relevance, reverse=True)

        # Trim to max items
        static_facts = static_facts[: self.STATIC_MAX_ITEMS]
        dynamic_facts = dynamic_facts[: self.DYNAMIC_MAX_ITEMS]

        # Version: increment from previous counter
        self._versions.setdefault(entity_id, 0)
        self._versions[entity_id] += 1
        version = self._versions[entity_id]

        profile = EntityProfile(
            entity_id=entity_id,
            static=static_facts,
            dynamic=dynamic_facts,
            memory_count=len(all_memories),
            computed_at=now.isoformat(),
            version=version,
        )

        logger.info(
            "profile.computed",
            entity_id=entity_id,
            static_count=len(static_facts),
            dynamic_count=len(dynamic_facts),
            total_memories=len(all_memories),
        )
        return profile
