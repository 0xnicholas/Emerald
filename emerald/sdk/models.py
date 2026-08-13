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
    conflicts_pending: list[dict] = field(default_factory=list)


@dataclass
class SearchPathStep:
    """One node/edge in a multihop result's provenance path (B4, #33).

    ``kind`` is "memory", "mention", or a relationship type (UPDATES /
    EXTENDS / DERIVES_FROM); ``id`` is the node id or the far-end memory
    id of an edge step.
    """

    kind: str
    id: str


@dataclass
class SearchResult:
    """A single search hit — either memory or RAG source."""

    id: str
    content: str
    summary: str = ""
    score: float = 0.0
    source: str = "memory"  # "memory" | "rag"
    memory_type: str = ""
    container_tag: str | None = None
    tags: list[str] = field(default_factory=list)
    is_latest: bool = True
    document_id: str | None = None
    document_title: str | None = None
    # Multihop provenance (B4, #33): seeds are depth 0 with an empty
    # path; graph-reached results carry hop depth and the full walk.
    depth: int = 0
    path: list[SearchPathStep] = field(default_factory=list)


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
    error_message: str | None = None
    # P1.2b: surface LLM fact-extraction outcome + final memory count.
    fact_extraction_status: str | None = None  # "success" | "failed" | "skipped" | None
    memory_count: int = 0  # number of memory nodes actually created in the graph
    # NOTE: ``chunk_count`` was removed from the schema; re-add here in the
    # same commit that re-introduces it on the server side.
