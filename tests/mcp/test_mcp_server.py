"""Tests for Emerald MCP Server tool registration and signatures.

These are unit tests — they verify the MCP server declares the correct tools
with the right names and parameters, without requiring a live Emerald API.

For integration tests (tool invocation against a real API), see tests/integration/.
"""

import pytest

from emerald.mcp.server import mcp


@pytest.mark.asyncio
async def test_mcp_add_tool_registered():
    """emerald_add tool is registered in the MCP server."""
    tools = await mcp.list_tools()
    assert any(t.name == "emerald_add" for t in tools)


@pytest.mark.asyncio
async def test_mcp_search_tool_registered():
    """emerald_search tool is registered in the MCP server."""
    tools = await mcp.list_tools()
    assert any(t.name == "emerald_search" for t in tools)


@pytest.mark.asyncio
async def test_mcp_profile_tool_registered():
    """emerald_profile tool is registered in the MCP server."""
    tools = await mcp.list_tools()
    assert any(t.name == "emerald_profile" for t in tools)


@pytest.mark.asyncio
async def test_mcp_tool_count():
    """Exactly 3 tools are registered (add, search, profile)."""
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    expected = {"emerald_add", "emerald_search", "emerald_profile"}
    assert tool_names == expected, f"Expected {expected}, got {tool_names}"


@pytest.mark.asyncio
async def test_mcp_add_tool_has_required_params():
    """emerald_add requires 'content' and 'entity_id' parameters."""
    tools = await mcp.list_tools()
    add_tool = next(t for t in tools if t.name == "emerald_add")
    params = add_tool.parameters
    assert "content" in params.get("properties", {})
    assert "entity_id" in params.get("properties", {})
    required = params.get("required", [])
    assert "content" in required
    assert "entity_id" in required


@pytest.mark.asyncio
async def test_mcp_search_tool_has_required_params():
    """emerald_search requires 'q' and 'entity_id' parameters."""
    tools = await mcp.list_tools()
    search_tool = next(t for t in tools if t.name == "emerald_search")
    params = search_tool.parameters
    assert "q" in params.get("properties", {})
    assert "entity_id" in params.get("properties", {})
    required = params.get("required", [])
    assert "q" in required
    assert "entity_id" in required


@pytest.mark.asyncio
async def test_mcp_profile_tool_has_required_params():
    """emerald_profile requires 'entity_id' parameter."""
    tools = await mcp.list_tools()
    profile_tool = next(t for t in tools if t.name == "emerald_profile")
    params = profile_tool.parameters
    assert "entity_id" in params.get("properties", {})
    required = params.get("required", [])
    assert "entity_id" in required


@pytest.mark.asyncio
async def test_mcp_add_tool_has_optional_params():
    """emerald_add has optional 'content_type' and 'metadata' parameters."""
    tools = await mcp.list_tools()
    add_tool = next(t for t in tools if t.name == "emerald_add")
    props = add_tool.parameters.get("properties", {})
    assert "content_type" in props
    assert "metadata" in props
    # These should NOT be in required
    required = add_tool.parameters.get("required", [])
    assert "content_type" not in required
    assert "metadata" not in required


@pytest.mark.asyncio
async def test_mcp_search_tool_has_optional_params():
    """emerald_search has optional 'search_mode' and 'top_k' parameters."""
    tools = await mcp.list_tools()
    search_tool = next(t for t in tools if t.name == "emerald_search")
    props = search_tool.parameters.get("properties", {})
    assert "search_mode" in props
    assert "top_k" in props
    required = search_tool.parameters.get("required", [])
    assert "search_mode" not in required
    assert "top_k" not in required
