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
async def test_list_spaces_default_first(graph):
    """Default space ('default') is always first in the list."""
    await graph.create_space("work", "Work", "💼", "user_001")
    await graph.create_space("default", "My Space", "📁", "user_001")

    spaces = await graph.list_spaces("user_001")
    assert spaces[0]["container_tag"] == "default"


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
async def test_delete_space_migrate_memories(graph):
    """Deleting a space with migrate_to_default=True re-assigns memories to default."""
    await graph.create_space("work", "Work", "💼", "user_001")
    await graph.create_space("default", "My Space", "📁", "user_001")

    mid1 = await graph.create_memory("Work memory", entity_id="user_001")
    mid2 = await graph.create_memory("Personal memory", entity_id="user_001")

    # Manually assign container_tag
    for m in graph._memories.get("user_001", []):
        if m["id"] == mid1:
            m["container_tag"] = "work"
        elif m["id"] == mid2:
            m["container_tag"] = "personal"

    # Delete the "work" space with migration
    await graph.delete_space("work", "user_001", migrate_to_default=True)

    # Verify space is gone
    spaces = await graph.list_spaces("user_001")
    tags = [s["container_tag"] for s in spaces]
    assert "work" not in tags

    # Verify memory was migrated to default
    migrated = [m for m in graph._memories["user_001"] if m["id"] == mid1]
    assert len(migrated) == 1
    assert migrated[0]["container_tag"] == "default"

    # Other memory should be unaffected
    other = [m for m in graph._memories["user_001"] if m["id"] == mid2]
    assert other[0]["container_tag"] == "personal"


@pytest.mark.asyncio
async def test_delete_space_no_migrate(graph):
    """Deleting a space without migration leaves container_tag untouched."""
    await graph.create_space("work", "Work", "💼", "user_001")

    mid = await graph.create_memory("Work memory", entity_id="user_001")
    for m in graph._memories.get("user_001", []):
        if m["id"] == mid:
            m["container_tag"] = "work"

    await graph.delete_space("work", "user_001", migrate_to_default=False)

    # Memory should still have the old container_tag
    memory = await graph.get_memory(mid)
    assert memory is not None
    assert memory.get("container_tag") == "work"


@pytest.mark.asyncio
async def test_ensure_default_spaces(graph):
    """ensure_default_spaces creates default Spaces for entities that need them."""
    # Create memories for two entities
    await graph.create_memory("Memory 1", entity_id="user_001")
    await graph.create_memory("Memory 1", entity_id="user_002")

    created = await graph.ensure_default_spaces()
    assert created == 2

    # Both entities should now have a default Space
    for eid in ("user_001", "user_002"):
        spaces = await graph.list_spaces(eid)
        tags = [s["container_tag"] for s in spaces]
        assert "default" in tags


@pytest.mark.asyncio
async def test_ensure_default_spaces_idempotent(graph):
    """ensure_default_spaces does not create duplicate default spaces."""
    await graph.create_memory("Memory", entity_id="user_001")

    created1 = await graph.ensure_default_spaces()
    assert created1 == 1

    created2 = await graph.ensure_default_spaces()
    assert created2 == 0

    spaces = await graph.list_spaces("user_001")
    defaults = [s for s in spaces if s["container_tag"] == "default"]
    assert len(defaults) == 1
