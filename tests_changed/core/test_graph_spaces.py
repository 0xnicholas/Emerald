"""Tests for GraphStore Space CRUD methods (in-memory only)."""

from __future__ import annotations

import pytest

from emerald.core.graph import GraphStore


@pytest.fixture
def graph():
    """Create a GraphStore with in-memory storage (no DB required)."""
    return GraphStore(use_db=False)


@pytest.mark.asyncio
async def test_create_space(graph):
    """Creating a space returns a space dict and persists it."""
    space = await graph.create_space(
        container_tag="work",
        name="Work",
        emoji="💼",
        entity_id="user_001",
    )
    assert space["container_tag"] == "work"
    assert space["name"] == "Work"
    assert space["emoji"] == "💼"
    assert space["entity_id"] == "user_001"
    assert "created_at" in space
    assert "updated_at" in space

    # Verify it's persisted via list
    spaces = await graph.list_spaces("user_001")
    tags = [s["container_tag"] for s in spaces]
    assert "work" in tags


@pytest.mark.asyncio
async def test_create_space_idempotent(graph):
    """Calling create_space twice with same args returns same space (MERGE semantics)."""
    space1 = await graph.create_space("work", "Work", "💼", "user_001")
    space2 = await graph.create_space("work", "Work", "💼", "user_001")

    assert space1["container_tag"] == space2["container_tag"]
    assert space1["entity_id"] == space2["entity_id"]

    # Should not create duplicates
    spaces = await graph.list_spaces("user_001")
    work_spaces = [s for s in spaces if s["container_tag"] == "work"]
    assert len(work_spaces) == 1


@pytest.mark.asyncio
async def test_list_spaces(graph):
    """Listing spaces returns all spaces for an entity in correct order."""
    await graph.create_space("personal", "Personal", "🏠", "user_001")
    await graph.create_space("work", "Work", "💼", "user_001")
    await graph.create_space("archive", "Archive", "📦", "user_001")

    spaces = await graph.list_spaces("user_001")
    assert len(spaces) >= 3

    # No 'default' space -- alphabetical by name
    names = [s["name"] for s in spaces]
    assert names == sorted(names)


@pytest.mark.asyncio
async def test_list_spaces_with_count(graph):
    """list_spaces returns memory_count per space."""
    await graph.create_space("work", "Work", "💼", "user_001")
    await graph.create_space("personal", "Personal", "🏠", "user_001")

    mid1 = await graph.create_memory("Work memory 1", entity_id="user_001")
    mid2 = await graph.create_memory("Work memory 2", entity_id="user_001")
    mid3 = await graph.create_memory("Personal memory", entity_id="user_001")

    # Manually assign container_tag on in-memory memories (Task 2 adds
    # this to create_memory; for now we set it directly for testing).
    for m in graph._memories.get("user_001", []):
        if m["id"] in (mid1, mid2):
            m["container_tag"] = "work"
        elif m["id"] == mid3:
            m["container_tag"] = "personal"

    spaces = await graph.list_spaces("user_001")
    work = [s for s in spaces if s["container_tag"] == "work"][0]
    personal = [s for s in spaces if s["container_tag"] == "personal"][0]

    assert work["memory_count"] == 2
    assert personal["memory_count"] == 1


@pytest.mark.asyncio
async def test_update_space(graph):
    """Updating a space changes its name and/or emoji."""
    await graph.create_space("work", "Work", "💼", "user_001")

    # Update name only
    updated = await graph.update_space("work", "user_001", name="Office")
    assert updated["name"] == "Office"
    assert updated["emoji"] == "💼"

    # Update emoji only
    updated = await graph.update_space("work", "user_001", emoji="🏢")
    assert updated["name"] == "Office"
    assert updated["emoji"] == "🏢"

    # Update both
    updated = await graph.update_space("work", "user_001", name="Work", emoji="💼")
    assert updated["name"] == "Work"
    assert updated["emoji"] == "💼"


@pytest.mark.asyncio
async def test_delete_space(graph):
    """Deleting a space removes it from the list."""
    await graph.create_space("work", "Work", "💼", "user_001")
    await graph.create_space("personal", "Personal", "🏠", "user_001")

    await graph.delete_space("work", "user_001")

    spaces = await graph.list_spaces("user_001")
    tags = [s["container_tag"] for s in spaces]
    assert "work" not in tags
    assert "personal" in tags


@pytest.mark.asyncio
async def test_delete_space_detaches_memories(graph):
    """Deleting a space with detach_memories=True nulls the memories' container_tag."""
    await graph.create_space("work", "Work", "💼", "user_001")

    mid1 = await graph.create_memory("Work memory", entity_id="user_001")
    mid2 = await graph.create_memory("Personal memory", entity_id="user_001")

    # Manually assign container_tag
    for m in graph._memories.get("user_001", []):
        if m["id"] == mid1:
            m["container_tag"] = "work"
        elif m["id"] == mid2:
            m["container_tag"] = "personal"

    # Delete the "work" space with detachment
    await graph.delete_space("work", "user_001", detach_memories=True)

    # Verify space is gone
    spaces = await graph.list_spaces("user_001")
    tags = [s["container_tag"] for s in spaces]
    assert "work" not in tags

    # Verify memory lost its space (null container_tag)
    migrated = [m for m in graph._memories["user_001"] if m["id"] == mid1]
    assert len(migrated) == 1
    assert migrated[0]["container_tag"] is None

    # Other memory should be unaffected
    other = [m for m in graph._memories["user_001"] if m["id"] == mid2]
    assert other[0]["container_tag"] == "personal"


@pytest.mark.asyncio
async def test_delete_space_no_migrate(graph):
    """Deleting a space without detachment leaves container_tag untouched."""
    await graph.create_space("work", "Work", "💼", "user_001")

    mid = await graph.create_memory("Work memory", entity_id="user_001")
    for m in graph._memories.get("user_001", []):
        if m["id"] == mid:
            m["container_tag"] = "work"

    await graph.delete_space("work", "user_001", detach_memories=False)

    # Memory should still have the old container_tag
    memory = await graph.get_memory(mid)
    assert memory is not None
    assert memory.get("container_tag") == "work"


@pytest.mark.asyncio
async def test_no_space_auto_creation(graph):
    """ADR-0002: the system never auto-creates or infers spaces.

    Memories without a container_tag stay space-less; no default space
    is created on their behalf.
    """
    await graph.create_memory("Memory 1", entity_id="user_001")

    spaces = await graph.list_spaces("user_001")
    assert spaces == []

    memory = await graph.get_memory(graph._memories["user_001"][0]["id"])
    assert memory.get("container_tag") is None


@pytest.mark.asyncio
async def test_update_memory_fields(graph):
    """update_memory() should update only the provided fields."""
    await graph.create_space("work", "Work", "💼", "user_test")
    await graph.create_memory(
        content="original content",
        entity_id="user_test",
        container_tag="work",
    )
    # Find the memory ID
    memories = graph._memories.get("user_test", [])
    assert len(memories) == 1
    mem_id = memories[0]["id"]
    assert memories[0]["content"] == "original content"

    # Update only content
    await graph.update_memory(mem_id, content="updated content")
    assert memories[0]["content"] == "updated content"
    assert memories[0]["memory_type"] == "fact"  # unchanged

    # Update only memory_type
    await graph.update_memory(mem_id, memory_type="preference")
    assert memories[0]["memory_type"] == "preference"
    assert memories[0]["content"] == "updated content"  # unchanged

    # Update multiple fields
    await graph.update_memory(mem_id, content="final", summary="a summary", confidence=0.95)
    assert memories[0]["content"] == "final"
    assert memories[0]["summary"] == "a summary"
    assert memories[0]["confidence"] == 0.95


@pytest.mark.asyncio
async def test_space_datetimes_neo4j_native(graph):
    """Regression（#52 走查 S2）：Neo4j 后端返回 neo4j.time.DateTime，SpaceResponse（Pydantic v2）
    拒绝非原生 datetime → /v1/spaces 必 500。_native_dt 必须转原生。"""
    from datetime import datetime as _dt

    from emerald.api.schemas import SpaceResponse
    from neo4j.time import DateTime as Neo4jDateTime

    neo_dt = Neo4jDateTime(2026, 8, 27, 12, 0, 0)
    converted = graph._native_dt(neo_dt)
    assert isinstance(converted, _dt)  # 原生 datetime，非 neo4j.time.DateTime

    space = await graph.create_space(
        container_tag="neo4j-dt", name="Neo4j DT", emoji="🧪", entity_id="user_neo"
    )
    # create_space 全链路产物必须可过 API schema（模拟路由层 SpaceResponse(**space)）
    SpaceResponse(**{**space, "created_at": converted, "updated_at": converted})
    # 非 datetime 值原样透传
    assert graph._native_dt(None) is None
    assert graph._native_dt("2026-08-27") == "2026-08-27"
