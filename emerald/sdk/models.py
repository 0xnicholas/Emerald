"""SDK data models — typed return values for all client methods.

Mirrors the REST API response schemas 1:1 (AGENTS.md requirement).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AddResult:
    """Returned by client.add()."""

    memory_ids: list[str]
    pipeline_status: str = "done"
    extracted_count: int = 0
    pipeline_id: str | None = None  # Set for async (file) uploads


@dataclass
class SearchResult:
    """A single search hit — either memory or RAG source."""

    id: str
    content: str
    summary: str = ""
    score: float = 0.0
    source: str = "memory"  # "memory" | "rag"
    memory_type: str = ""
    is_latest: bool = True
    document_id: str | None = None
    document_title: str | None = None


@dataclass
class SearchResults:
    """Returned by client.search()."""

    results: list[SearchResult] = field(default_factory=list)
    search_mode: str = "hybrid"
    query_rewritten: str | None = None


@dataclass
class ProfileFact:
    """A single fact in an entity profile."""

    content: str
    importance: float = 1.0
    relevance: float = 1.0
    source: str = ""
    acquired_at: str = ""


@dataclass
class Profile:
    """Returned by client.profile()."""

    entity_id: str
    static: list[ProfileFact] = field(default_factory=list)
    dynamic: list[ProfileFact] = field(default_factory=list)
    memory_count: int = 0
    computed_at: str = ""
    version: int = 1


@dataclass
class HealthStatus:
    """Returned by client.health()."""

    status: str
    version: str
    checks: dict = field(default_factory=dict)


@dataclass
class PipelineStatus:
    """Returned by client.pipeline_status()."""

    pipeline_id: str
    status: str
    stage: str = ""
    document_id: str | None = None
    content_type: str = ""
    chunk_count: int = 0
    error_message: str | None = None
