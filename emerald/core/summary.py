# Memory summary builder — export entity memory as a MEMORY.md-style Markdown document.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from emerald.core.graph import GraphStore
from emerald.core.profile import ProfileManager

logger = structlog.get_logger(__name__)


class MemorySummaryBuilder:
    """Build a human-readable Markdown summary of an entity's memory.

    The output is intentionally simple and stable: it can be written to a
    MEMORY.md file in a project repo, or returned to an agent as context.
    """

    def __init__(
        self,
        graph: GraphStore | None = None,
        profile_manager: ProfileManager | None = None,
    ) -> None:
        self.graph = graph or GraphStore(use_db=False)
        self.profile_manager = profile_manager or ProfileManager(graph=self.graph)

    async def build(
        self,
        entity_id: str,
        *,
        max_recent: int = 10,
        include_source_ids: bool = False,
    ) -> str:
        """Build a Markdown summary for ``entity_id``.

        Args:
            entity_id: The entity to summarize.
            max_recent: Maximum number of recent episodic/observation memories.
            include_source_ids: Include memory IDs (useful for debugging).

        Returns:
            Markdown string.
        """
        profile = await self.profile_manager.get(entity_id)
        recent_memories = await self._recent_memories(entity_id, max_recent)

        lines: list[str] = []
        lines.append(f"# Memory Summary: {entity_id}")
        lines.append("")
        lines.append(f"_Generated at {datetime.now(UTC).isoformat()}_")
        lines.append("")

        # Static facts
        if profile.static:
            lines.append("## Static Facts")
            lines.append("")
            for fact in profile.static:
                item = f"- {fact.content}"
                if include_source_ids and fact.memory_id:
                    item += f" `({fact.memory_id})`"
                lines.append(item)
            lines.append("")
        else:
            lines.append("## Static Facts")
            lines.append("")
            lines.append("_No static facts yet._")
            lines.append("")

        # Dynamic / recent context
        if profile.dynamic:
            lines.append("## Recent Context")
            lines.append("")
            for fact in profile.dynamic:
                item = f"- {fact.content}"
                if fact.source:
                    item += f" (source: {fact.source})"
                if include_source_ids and fact.memory_id:
                    item += f" `({fact.memory_id})`"
                lines.append(item)
            lines.append("")

        # Recent raw memories (including observations, errors, learnings)
        if recent_memories:
            lines.append("## Recent Memories")
            lines.append("")
            for memory in recent_memories:
                item = f"- {memory.get('content', '')}"
                mtype = memory.get("internal_type") or memory.get("memory_type", "fact")
                item += f" _({mtype})_"
                if include_source_ids:
                    item += f" `({memory.get('id')})`"
                lines.append(item)
            lines.append("")

        lines.append("---")
        lines.append(f"_Total memories: {profile.memory_count}_")
        return "\n".join(lines)

    async def _recent_memories(
        self, entity_id: str, limit: int
    ) -> list[dict[str, Any]]:
        """Fetch recent non-static memories for the summary."""
        cutoff = datetime.now(UTC) - timedelta(days=7)
        memories = await self.graph.list_latest_memories(
            entity_id, limit=limit * 3,
        )
        recent = [
            m for m in memories
            if m.get("created_at", datetime.now(UTC)) > cutoff
            and m.get("memory_type") != "fact"
        ]
        # Prefer memories with fine internal types (observation, learning, error)
        typed = [m for m in recent if m.get("internal_type")]
        untyped = [m for m in recent if not m.get("internal_type")]
        return (typed + untyped)[:limit]
