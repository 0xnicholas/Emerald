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

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import structlog

from emerald.core.graph import GraphStore
from emerald.core.metrics import (
    profile_cache_hit_total,
    profile_cache_miss_total,
    profile_compute_latency_seconds,
    timed,
)
from emerald.core.tracing import get_tracer

logger = structlog.get_logger(__name__)


@dataclass
class ProfileFact:
    content: str
    importance: float = 1.0
    relevance: float = 1.0
    source: str = ""
    acquired_at: str = ""
    memory_id: str = ""


@dataclass
class EntityProfile:
    entity_id: str
    static: list[ProfileFact] = field(default_factory=list)
    dynamic: list[ProfileFact] = field(default_factory=list)
    memory_count: int = 0
    computed_at: str = ""
    version: int = 1
    source_memory_ids: list[str] = field(default_factory=list)


class ProfileManager:
    """Manages entity profiles: compute, cache, invalidate, incremental refresh.

    Uses Redis in production; in-memory dict fallback for tests without Redis.
    """

    STATIC_CONFIDENCE_MIN = 0.5
    DYNAMIC_CONFIDENCE_MIN = 0.3
    DYNAMIC_LOOKBACK_DAYS = 7
    STATIC_MAX_ITEMS = 10
    DYNAMIC_MAX_ITEMS = 5
    TTL = 24 * 3600

    def __init__(
        self,
        graph: GraphStore | None = None,
        redis_client=None,
    ) -> None:
        self.graph = graph or GraphStore(use_db=False)
        self._redis = redis_client
        self._memory_cache: dict[str, EntityProfile] = {}
        self._versions: dict[str, int] = {}

    def _get_redis(self):
        if self._redis is not None:
            return self._redis
        try:
            from emerald.db.redis import get_redis_client
            return get_redis_client()
        except RuntimeError:
            return None

    async def get(self, entity_id: str) -> EntityProfile:
        """Get entity profile. Checks Redis cache first, computes on miss.

        Target: ~50ms when cached.
        """
        tracer = get_tracer()
        with tracer.start_as_current_span("profile.get") as span:
            span.set_attribute("entity_id", entity_id)
            # Check in-memory fallback first (tests without Redis)
            if entity_id in self._memory_cache:
                logger.debug("profile.cache.hit", entity_id=entity_id, backend="memory")
                profile_cache_hit_total.labels(backend="memory").inc()
                return self._memory_cache[entity_id]

            redis = self._get_redis()
            if redis:
                cached = await redis.get(f"profile:{entity_id}")
                if cached:
                    logger.debug("profile.cache.hit", entity_id=entity_id, backend="redis")
                    profile_cache_hit_total.labels(backend="redis").inc()
                    data = json.loads(cached)
                    return self._deserialize_profile(data)

            logger.info("profile.cache.miss", entity_id=entity_id)
            profile_cache_miss_total.inc()
            profile = await self.compute(entity_id)
            await self._set_cached_profile(entity_id, profile)
            return profile

    async def invalidate(self, entity_id: str) -> None:
        """Invalidate profile cache after new memories are ingested.

        Called at the end of the pipeline INDEXING stage.
        """
        redis = self._get_redis()
        if redis:
            await redis.delete(f"profile:{entity_id}")
            logger.info("profile.cache.invalidated", entity_id=entity_id)
        if entity_id in self._memory_cache:
            del self._memory_cache[entity_id]

    async def refresh(
        self, entity_id: str, new_memory_ids: list[str] | None = None
    ) -> None:
        """Refresh profile after new memories are ingested.

        If *new_memory_ids* is provided and a cached profile exists, performs
        an incremental merge. Otherwise falls back to full invalidation.
        """
        tracer = get_tracer()
        with tracer.start_as_current_span("profile.refresh") as span:
            span.set_attribute("entity_id", entity_id)
            span.set_attribute("new_memory_count", len(new_memory_ids or []))

            if not new_memory_ids:
                await self.invalidate(entity_id)
                return

            cached = await self._get_cached_raw(entity_id)
            if cached is None:
                # No existing cache — invalidate so next get() computes fresh
                await self.invalidate(entity_id)
                return

            profile = self._deserialize_profile(cached)
            merged = await self._merge_incremental(entity_id, profile, new_memory_ids)
            await self._set_cached_profile(entity_id, merged)
            logger.info(
                "profile.refreshed.incremental",
                entity_id=entity_id,
                static_count=len(merged.static),
                dynamic_count=len(merged.dynamic),
                version=merged.version,
            )

    async def compute(self, entity_id: str) -> EntityProfile:
        """Compute profile from the graph store.

        Static facts: fact/preference type, confidence >= 0.5, is_latest=True
        Dynamic facts: episodic type, created within 7 days, confidence >= 0.3
        """
        tracer = get_tracer()
        with tracer.start_as_current_span("profile.compute") as span:
            span.set_attribute("entity_id", entity_id)
            with timed(profile_compute_latency_seconds):
                all_memories = await self.graph.list_latest_memories(entity_id, limit=200)
                now = datetime.now(UTC)
                cutoff = now - timedelta(days=self.DYNAMIC_LOOKBACK_DAYS)

                static_facts: list[ProfileFact] = []
                dynamic_facts: list[ProfileFact] = []
                source_ids: list[str] = []

                for m in all_memories:
                    memory_type = m.get("memory_type", "fact")
                    confidence = m.get("confidence", 0.5)
                    created_at = m.get("created_at", now)
                    content = m.get("content", "")
                    mid = m.get("id", "")

                    # Compute multi-factor importance score
                    importance = ProfileManager._compute_importance(
                        m, now=now, cutoff=cutoff
                    )

                    # Static: fact or preference with high confidence
                    if memory_type in ("fact", "preference") and confidence >= self.STATIC_CONFIDENCE_MIN:
                        static_facts.append(
                            ProfileFact(
                                content=content,
                                importance=importance,
                                acquired_at=created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
                                memory_id=mid,
                            )
                        )
                        source_ids.append(mid)

                    # Dynamic: episodic and recent
                    if memory_type == "episodic" and confidence >= self.DYNAMIC_CONFIDENCE_MIN:
                        if hasattr(created_at, "isoformat"):
                            if created_at >= cutoff:
                                dynamic_facts.append(
                                    ProfileFact(
                                        content=content,
                                        relevance=importance,
                                        source="最近对话",
                                        acquired_at=created_at.isoformat(),
                                        memory_id=mid,
                                    )
                                )
                                source_ids.append(mid)
                        else:
                            dynamic_facts.append(
                                ProfileFact(
                                    content=content,
                                    relevance=importance,
                                    source="最近对话",
                                    memory_id=mid,
                                )
                            )
                            source_ids.append(mid)

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
                    source_memory_ids=source_ids,
                )

                logger.info(
                    "profile.computed",
                    entity_id=entity_id,
                    static_count=len(static_facts),
                    dynamic_count=len(dynamic_facts),
                    total_memories=len(all_memories),
                )
                return profile

    # ------------------------------------------------------------------
    # Importance scoring
    # ------------------------------------------------------------------

    # Weight factors for multi-factor importance scoring
    WEIGHT_CONFIDENCE = 0.35
    WEIGHT_RECENCY = 0.25
    WEIGHT_TYPE = 0.20
    WEIGHT_RELATIONSHIPS = 0.20

    TYPE_WEIGHTS = {"preference": 1.0, "fact": 0.8, "episodic": 0.5, "noise": 0.2}

    @classmethod
    def _compute_importance(
        cls,
        memory: dict,
        now: datetime | None = None,
        cutoff: datetime | None = None,
    ) -> float:
        """Compute a multi-factor importance score for a memory.

        Combines:
        - Confidence (from chunker/LLM)              — 35%
        - Recency (newer = higher, exponential decay) — 25%
        - Memory type weight                          — 20%
        - Relationship count (linked memories)        — 20%
        """
        if now is None:
            now = datetime.now(UTC)

        confidence = memory.get("confidence", 0.5)
        mem_type = memory.get("memory_type", "fact")
        created_at = memory.get("created_at", now)
        rels = memory.get("relationships", [])

        # Normalize created_at to Python datetime
        if hasattr(created_at, "to_native"):
            created_at = created_at.to_native()
        elif isinstance(created_at, str):
            from datetime import datetime as dt
            created_at = dt.fromisoformat(created_at.replace("Z", "+00:00"))

        # Recency: exponential decay, half-life = 30 days
        days_ago = max(0, (now - created_at).total_seconds() / 86400)
        recency = 2.0 ** (-days_ago / 30.0)

        # Type weight
        type_weight = cls.TYPE_WEIGHTS.get(mem_type, 0.5)

        # Relationship count: normalize to [0, 1]
        rel_count = len(rels) if isinstance(rels, list) else 0
        rel_score = min(rel_count / 10.0, 1.0)

        score = (
            cls.WEIGHT_CONFIDENCE * confidence
            + cls.WEIGHT_RECENCY * recency
            + cls.WEIGHT_TYPE * type_weight
            + cls.WEIGHT_RELATIONSHIPS * rel_score
        )

        return round(min(score, 1.0), 4)

    # ------------------------------------------------------------------
    # Incremental merge helpers
    # ------------------------------------------------------------------

    async def _merge_incremental(
        self,
        entity_id: str,
        profile: EntityProfile,
        new_memory_ids: list[str],
    ) -> EntityProfile:
        """Merge new memories into an existing profile."""
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=self.DYNAMIC_LOOKBACK_DAYS)

        # 1. Find UPDATES relationships: new memories that replace existing ones
        updates = await self.graph.get_relationships_to(profile.source_memory_ids)
        evicted_ids = set()
        for old_id, new_ids in updates.items():
            if any(nid in new_memory_ids for nid in new_ids):
                evicted_ids.add(old_id)

        # Evict replaced facts using memory_id on each ProfileFact
        if evicted_ids:
            profile.static = [f for f in profile.static if f.memory_id not in evicted_ids]
            profile.dynamic = [f for f in profile.dynamic if f.memory_id not in evicted_ids]

        # 2. Add new qualifying memories
        for mid in new_memory_ids:
            m = await self.graph.get_memory(mid)
            if not m:
                continue
            memory_type = m.get("memory_type", "fact")
            confidence = m.get("confidence", 0.5)
            created_at = m.get("created_at", now)
            content = m.get("content", "")

            if memory_type in ("fact", "preference") and confidence >= self.STATIC_CONFIDENCE_MIN:
                profile.static.append(
                    ProfileFact(
                        content=content,
                        importance=confidence,
                        acquired_at=created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
                        memory_id=mid,
                    )
                )

            if memory_type == "episodic" and confidence >= self.DYNAMIC_CONFIDENCE_MIN:
                is_recent = True
                if hasattr(created_at, "isoformat"):
                    is_recent = created_at >= cutoff
                if is_recent:
                    profile.dynamic.append(
                        ProfileFact(
                            content=content,
                            relevance=confidence,
                            source="最近对话",
                            acquired_at=created_at.isoformat() if hasattr(created_at, "isoformat") else "",
                            memory_id=mid,
                        )
                    )

        # 3. Evict expired dynamic facts
        profile.dynamic = [
            f for f in profile.dynamic
            if self._is_recent(f.acquired_at, cutoff)
        ]

        # 4. Re-sort and trim
        profile.static.sort(key=lambda f: f.importance, reverse=True)
        profile.dynamic.sort(key=lambda f: f.relevance, reverse=True)
        profile.static = profile.static[: self.STATIC_MAX_ITEMS]
        profile.dynamic = profile.dynamic[: self.DYNAMIC_MAX_ITEMS]

        # Rebuild source_memory_ids from facts so it stays in sync after sort/trim
        profile.source_memory_ids = [f.memory_id for f in profile.static + profile.dynamic]

        profile.version += 1
        profile.computed_at = now.isoformat()
        return profile

    @staticmethod
    def _is_recent(acquired_at: str, cutoff: datetime) -> bool:
        """Check if an acquired_at timestamp is within the cutoff."""
        if not acquired_at:
            return True
        try:
            dt = datetime.fromisoformat(acquired_at.replace("Z", "+00:00"))
            return dt >= cutoff
        except ValueError:
            return True

    # ------------------------------------------------------------------
    # Cache I/O
    # ------------------------------------------------------------------

    def _deserialize_profile(self, data: dict) -> EntityProfile:
        return EntityProfile(
            entity_id=data["entity_id"],
            static=[ProfileFact(**f) for f in data.get("static", [])],
            dynamic=[ProfileFact(**f) for f in data.get("dynamic", [])],
            memory_count=data.get("memory_count", 0),
            computed_at=data.get("computed_at", ""),
            version=data.get("version", 1),
            source_memory_ids=data.get("source_memory_ids", []),
        )

    def _serialize_profile(self, profile: EntityProfile) -> dict:
        return {
            "entity_id": profile.entity_id,
            "static": [
                {"content": f.content, "importance": f.importance, "memory_id": f.memory_id}
                for f in profile.static
            ],
            "dynamic": [
                {
                    "content": f.content,
                    "relevance": f.relevance,
                    "source": f.source,
                    "acquired_at": f.acquired_at,
                    "memory_id": f.memory_id,
                }
                for f in profile.dynamic
            ],
            "memory_count": profile.memory_count,
            "computed_at": profile.computed_at,
            "version": profile.version,
            "source_memory_ids": profile.source_memory_ids,
        }

    async def _get_cached_raw(self, entity_id: str) -> dict | None:
        """Return raw cached profile dict, or None if not cached."""
        if entity_id in self._memory_cache:
            return self._serialize_profile(self._memory_cache[entity_id])
        redis = self._get_redis()
        if redis:
            cached = await redis.get(f"profile:{entity_id}")
            if cached:
                return json.loads(cached)
        return None

    async def _set_cached_profile(self, entity_id: str, profile: EntityProfile) -> None:
        redis = self._get_redis()
        if redis:
            await redis.setex(
                f"profile:{entity_id}",
                self.TTL,
                json.dumps(self._serialize_profile(profile)),
            )
        else:
            self._memory_cache[entity_id] = profile
