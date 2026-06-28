"""Emerald MCP Server — exposes memory operations as MCP tools.

Exposes three tools to any MCP-compatible client (Claude Desktop, Cursor, etc.):
- emerald_add: Store a memory for an entity
- emerald_search: Search memories and documents
- emerald_profile: Retrieve an entity's profile (static + dynamic facts)

Usage:
    # stdio (default, for Claude Desktop)
    EMERALD_API_KEY=em_xxx python -m emerald.mcp.server --transport stdio

    # SSE (HTTP, for remote clients)
    EMERALD_API_KEY=em_xxx python -m emerald.mcp.server --transport sse --port 8001

Env:
    EMERALD_API_KEY — required. API key for Emerald REST API.
    EMERALD_BASE_URL — optional. Default: http://localhost:8000
"""

from __future__ import annotations

import argparse
import os

from fastmcp import FastMCP

from emerald.sdk.client import EmeraldClient

mcp = FastMCP("emerald")

_client: EmeraldClient | None = None


def _get_client() -> EmeraldClient:
    global _client
    if _client is None:
        api_key = os.environ.get("EMERALD_API_KEY")
        if not api_key:
            raise RuntimeError(
                "EMERALD_API_KEY environment variable is required. "
                "Set it before starting the MCP server."
            )
        base_url = os.environ.get("EMERALD_BASE_URL", "http://localhost:8000")
        _client = EmeraldClient(api_key=api_key, base_url=base_url)
    return _client


# ── MCP Tools ────────────────────────────────────────────────────────────


@mcp.tool()
async def emerald_add(
    content: str,
    entity_id: str,
    content_type: str = "text",
    metadata: dict | None = None,
) -> dict:
    """Add a memory to Emerald.

    Args:
        content: The text content to remember.
        entity_id: The entity (user, project, org) to associate the memory with.
        content_type: Content type hint — "text", "conversation", "markdown", etc.
        metadata: Optional key-value metadata dict (e.g. {"session_id": "..."}).
    """
    client = _get_client()
    result = await client.add(
        content=content,
        entity_id=entity_id,
        content_type=content_type,
        metadata=metadata,
    )
    return {
        "memory_ids": result.memory_ids,
        "pipeline_status": result.pipeline_status,
        "extracted_count": result.extracted_count,
    }


@mcp.tool()
async def emerald_search(
    q: str,
    entity_id: str,
    search_mode: str = "hybrid",
    top_k: int = 30,
    min_confidence: float | None = None,
    dynamic_truncation: bool = True,
) -> dict:
    """Search memories and documents in Emerald.

    Args:
        q: The search query.
        entity_id: The entity to search within.
        search_mode: One of "hybrid" (default), "memory", or "rag".
        top_k: Maximum number of results to return (1–100).
        min_confidence: Minimum memory confidence (0-1).
        dynamic_truncation: Stop when score gap exceeds threshold.
    """
    client = _get_client()
    result = await client.search(
        q=q,
        entity_id=entity_id,
        search_mode=search_mode,
        top_k=top_k,
        min_confidence=min_confidence,
        dynamic_truncation=dynamic_truncation,
    )
    return {
        "results": [
            {
                "id": r.id,
                "content": r.content,
                "summary": r.summary,
                "score": r.score,
                "source": r.source,
                "memory_type": r.memory_type,
                "is_latest": r.is_latest,
            }
            for r in result.results
        ],
        "search_mode": result.search_mode,
    }


@mcp.tool()
async def emerald_profile(entity_id: str) -> dict:
    """Get the user profile from Emerald.

    Returns static facts (long-term, always relevant) and dynamic facts
    (recent, episodic context). This is the fastest way for an agent to
    know who it's talking to — no search query needed.

    Args:
        entity_id: The entity to profile.
    """
    client = _get_client()
    result = await client.profile(entity_id=entity_id)
    return {
        "entity_id": result.entity_id,
        "static": [f.content for f in result.static],
        "dynamic": [f.content for f in result.dynamic],
        "memory_count": result.memory_count,
    }


# ── Entry point ──────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Emerald MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8001,
        help="Port for SSE transport (default: 8001)",
    )
    args = parser.parse_args()

    if args.transport == "sse":
        mcp.run(transport="sse", port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
