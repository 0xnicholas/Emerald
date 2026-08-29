"""Tests for MEMORY.md / daily summary export."""

import pytest

from emerald.core.graph import GraphStore
from emerald.core.summary import MemorySummaryBuilder


@pytest.fixture
def builder():
    graph = GraphStore(use_db=False)
    return MemorySummaryBuilder(graph=graph)


@pytest.mark.asyncio
async def test_summary_includes_static_facts(builder):
    """Static facts from the profile appear in the Markdown output."""
    await builder.graph.create_memory(
        "用户是资深前端工程师",
        entity_id="user_123",
        memory_type="fact",
        confidence=0.9,
    )
    await builder.graph.create_memory(
        "用户偏好 TypeScript",
        entity_id="user_123",
        memory_type="preference",
        confidence=0.85,
    )

    # Force profile refresh
    await builder.profile_manager.refresh("user_123")

    markdown = await builder.build("user_123")
    assert "# Memory Summary: user_123" in markdown
    assert "## Static Facts" in markdown
    assert "资深前端工程师" in markdown
    assert "TypeScript" in markdown


@pytest.mark.asyncio
async def test_summary_for_empty_entity(builder):
    """Empty entities produce a valid but minimal summary."""
    markdown = await builder.build("empty_entity")
    assert "# Memory Summary: empty_entity" in markdown
    assert "No static facts yet" in markdown
