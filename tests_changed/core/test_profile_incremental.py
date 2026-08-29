"""Tests for profile incremental update (refresh) logic."""

from __future__ import annotations

import pytest

from emerald.core.graph import GraphStore
from emerald.core.profile import EntityProfile, ProfileFact, ProfileManager


class TestProfileIncremental:
    """Verify incremental profile updates avoid full recomputation where possible."""

    @pytest.fixture
    def graph(self):
        return GraphStore(use_db=False)

    @pytest.fixture
    def mgr(self, graph):
        return ProfileManager(graph=graph)

    @pytest.fixture
    def entity_id(self):
        return "user_42"

    async def _add_memory(self, graph, entity_id, content, memory_type="fact", confidence=0.8):
        return await graph.create_memory(
            content=content,
            entity_id=entity_id,
            memory_type=memory_type,
            confidence=confidence,
        )

    async def test_full_compute_includes_source_memory_ids(self, mgr, graph, entity_id):
        mid = await self._add_memory(graph, entity_id, "Works at Google", "fact", 0.9)
        profile = await mgr.compute(entity_id)
        assert mid in profile.source_memory_ids
        assert len(profile.static) == 1

    async def test_refresh_with_no_cache_falls_back_to_invalidate(self, mgr, graph, entity_id):
        mid = await self._add_memory(graph, entity_id, "Lives in Tokyo", "fact", 0.8)
        await mgr.refresh(entity_id, [mid])
        # No cache exists, so it was invalidated; next get() should compute
        profile = await mgr.get(entity_id)
        assert mid in profile.source_memory_ids

    async def test_incremental_adds_new_static_fact(self, mgr, graph, entity_id):
        mid1 = await self._add_memory(graph, entity_id, "Speaks Japanese", "fact", 0.85)
        profile = await mgr.compute(entity_id)
        await mgr._set_cached_profile(entity_id, profile)

        mid2 = await self._add_memory(graph, entity_id, "Speaks French", "fact", 0.8)
        await mgr.refresh(entity_id, [mid2])

        refreshed = await mgr.get(entity_id)
        contents = {f.content for f in refreshed.static}
        assert "Speaks Japanese" in contents
        assert "Speaks French" in contents
        assert mid1 in refreshed.source_memory_ids
        assert mid2 in refreshed.source_memory_ids

    async def test_incremental_adds_new_dynamic_fact(self, mgr, graph, entity_id):
        mid1 = await self._add_memory(graph, entity_id, "Had lunch with Alice", "episodic", 0.6)
        profile = await mgr.compute(entity_id)
        await mgr._set_cached_profile(entity_id, profile)

        mid2 = await self._add_memory(graph, entity_id, "Went hiking", "episodic", 0.7)
        await mgr.refresh(entity_id, [mid2])

        refreshed = await mgr.get(entity_id)
        contents = {f.content for f in refreshed.dynamic}
        assert "Had lunch with Alice" in contents
        assert "Went hiking" in contents

    async def test_updates_relation_replaces_old_fact(self, mgr, graph, entity_id):
        old_mid = await self._add_memory(graph, entity_id, "Works at Google", "fact", 0.9)
        profile = await mgr.compute(entity_id)
        await mgr._set_cached_profile(entity_id, profile)

        new_mid = await self._add_memory(graph, entity_id, "Works at Apple", "fact", 0.9)
        # Simulate an UPDATES relationship from new to old
        await graph.create_relationship(new_mid, old_mid, "UPDATES", {"reason": "job change"})

        await mgr.refresh(entity_id, [new_mid])
        refreshed = await mgr.get(entity_id)
        contents = {f.content for f in refreshed.static}
        assert "Works at Google" not in contents
        assert "Works at Apple" in contents

    async def test_refresh_without_new_ids_invalidates(self, mgr, graph, entity_id):
        mid = await self._add_memory(graph, entity_id, "Likes sushi", "fact", 0.8)
        profile = await mgr.compute(entity_id)
        await mgr._set_cached_profile(entity_id, profile)

        await mgr.refresh(entity_id, None)
        # After invalidate, get() should recompute
        refreshed = await mgr.get(entity_id)
        assert "Likes sushi" in {f.content for f in refreshed.static}

    async def test_static_max_items_enforced_after_incremental(self, mgr, graph, entity_id):
        mids = []
        for i in range(12):
            mid = await self._add_memory(graph, entity_id, f"Fact {i}", "fact", 0.9)
            mids.append(mid)

        profile = await mgr.compute(entity_id)
        await mgr._set_cached_profile(entity_id, profile)
        assert len(profile.static) == 10  # max

        new_mid = await self._add_memory(graph, entity_id, "Extra fact", "fact", 0.95)
        await mgr.refresh(entity_id, [new_mid])

        refreshed = await mgr.get(entity_id)
        assert len(refreshed.static) <= 10
        # Highest importance should be at top
        assert refreshed.static[0].content == "Extra fact"
