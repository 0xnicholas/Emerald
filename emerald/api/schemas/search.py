"""Search API schemas — request/response models for /v1/search."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    q: str = Field(default="", examples=["用户偏好什么编程语言？"])
    entity_id: str = Field(examples=["user_123"])
    search_mode: str = Field(default="hybrid", examples=["hybrid"])  # hybrid | memory | rag
    top_k: int = Field(default=30, ge=1, le=100)
    rerank: bool = False
    rewrite_query: bool = False
    filters: dict | None = None
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    dynamic_truncation: bool = Field(default=True)
    about: str | None = Field(
        default=None,
        description="Entity-centric retrieval (B4): a mention canonical form "
        "or mention id — returns the entity's memories mentioning it "
        "across all surface forms. Skips RAG and fast-lane paths.",
    )
    depth: int = Field(
        default=0,
        ge=0,
        le=4,  # must match MAX_DEPTH (emerald/core/multihop.py)
        description="Graph traversal hops over shared-subject mention bridges "
        "(B4). 0 = status quo; >=1 walks Memory-MENTIONS->Mention<-MENTIONS-Memory.",
    )


class SearchResultItem(BaseModel):
    id: str
    content: str
    summary: str = ""
    score: float = 0.0
    source: str = "memory"  # memory | rag
    memory_type: str = ""
    container_tag: str | None = None
    tags: list[str] = []
    is_latest: bool = True
    document_id: str | None = None
    document_title: str | None = None
    created_at: str | None = None


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    search_mode: str
    query_rewritten: str | None = None
