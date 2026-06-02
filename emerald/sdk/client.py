"""Emerald Python SDK client.

Four core methods mirroring the REST API:
- add(content, entity_id)       → POST /v1/memories
- search(q, entity_id)          → POST /v1/search
- profile(entity_id)            → GET /v1/profiles/{id}
- upload(file, entity_id)       → POST /v1/upload

AGENTS.md: "SDK 不得暴露内部图谱操作。公共 API 仅限 add/search/profile/upload。"
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, BinaryIO

import httpx

from emerald.sdk.models import (
    AddResult,
    HealthStatus,
    PipelineStatus,
    Profile,
    ProfileFact,
    SearchResult,
    SearchResults,
)


class EmeraldClient:
    """Async client for the Emerald memory API.

    Usage:
        client = EmeraldClient(api_key="em_xxx")
        result = await client.add("用户喜欢 TypeScript", entity_id="user_123")
        profile = await client.profile("user_123")
        results = await client.search("TypeScript", entity_id="user_123")
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str = "v1",
    ) -> None:
        self.api_key = api_key or os.environ.get("EMERALD_API_KEY", "")
        self.base_url = (base_url or os.environ.get("EMERALD_BASE_URL", "http://localhost:8000")).rstrip("/")
        self.api_version = api_version
        self._headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self._headers,
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ---- Core methods ----

    async def add(
        self,
        content: str,
        *,
        entity_id: str,
        content_type: str = "text",
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AddResult:
        """Add content to the memory graph.

        Args:
            content: Text content to ingest.
            entity_id: Entity (user, project, org) this content belongs to.
            content_type: Content type hint (auto-detected if omitted).
            title: Optional content title.
            metadata: Optional key-value metadata.

        Returns:
            AddResult with memory IDs and pipeline status.
        """
        client = await self._get_client()
        body: dict[str, Any] = {
            "content": content,
            "entity_id": entity_id,
            "content_type": content_type,
        }
        if title:
            body["title"] = title
        if metadata:
            body["metadata"] = metadata

        response = await client.post(f"/{self.api_version}/memories", json=body)
        response.raise_for_status()
        data = response.json()["data"]
        return AddResult(
            memory_ids=data["memory_ids"],
            pipeline_status=data.get("pipeline_status", "done"),
            extracted_count=data.get("extracted_count", 0),
            pipeline_id=data.get("pipeline_id"),
        )

    async def search(
        self,
        q: str,
        *,
        entity_id: str,
        search_mode: str = "hybrid",
        top_k: int = 10,
        rerank: bool = False,
        rewrite_query: bool = False,
        filters: dict[str, Any] | None = None,
    ) -> SearchResults:
        """Hybrid search across memory (graph) and RAG (vector).

        Args:
            q: Search query.
            entity_id: Entity scope.
            search_mode: 'hybrid', 'memory', or 'rag'.
            top_k: Max results (1-100).
            rerank: Enable cross-encoder re-ranking.
            rewrite_query: Enable LLM query expansion.
            filters: Metadata filters (e.g., {"memory_type": "preference"}).

        Returns:
            SearchResults with scored, deduplicated hits.
        """
        client = await self._get_client()
        body: dict[str, Any] = {
            "q": q,
            "entity_id": entity_id,
            "search_mode": search_mode,
            "top_k": top_k,
            "rerank": rerank,
            "rewrite_query": rewrite_query,
        }
        if filters:
            body["filters"] = filters

        response = await client.post(f"/{self.api_version}/search", json=body)
        response.raise_for_status()
        data = response.json()["data"]

        return SearchResults(
            results=[
                SearchResult(
                    id=r["id"],
                    content=r["content"],
                    summary=r.get("summary", ""),
                    score=r.get("score", 0.0),
                    source=r.get("source", "memory"),
                    memory_type=r.get("memory_type", ""),
                    is_latest=r.get("is_latest", True),
                    document_id=r.get("document_id"),
                    document_title=r.get("document_title"),
                )
                for r in data.get("results", [])
            ],
            search_mode=data.get("search_mode", search_mode),
            query_rewritten=data.get("query_rewritten"),
        )

    async def profile(self, entity_id: str) -> Profile:
        """Get entity profile (static + dynamic facts).

        Target latency: ~50ms from cache.

        Args:
            entity_id: The entity to profile.

        Returns:
            Profile with static facts (always relevant) and dynamic facts (recent, episodic).
        """
        client = await self._get_client()
        response = await client.get(f"/{self.api_version}/profiles/{entity_id}")
        response.raise_for_status()
        data = response.json()["data"]

        return Profile(
            entity_id=data["entity_id"],
            static=[
                ProfileFact(
                    content=f["content"],
                    importance=f.get("importance", 1.0),
                )
                for f in data.get("static", [])
            ],
            dynamic=[
                ProfileFact(
                    content=f["content"],
                    relevance=f.get("relevance", 1.0),
                    source=f.get("source", ""),
                    acquired_at=f.get("acquired_at", ""),
                )
                for f in data.get("dynamic", [])
            ],
            memory_count=data.get("memory_count", 0),
            computed_at=data.get("computed_at", ""),
            version=data.get("version", 1),
        )

    async def upload(
        self,
        file: BinaryIO | bytes | str,
        *,
        entity_id: str,
        content_type: str | None = None,
        title: str | None = None,
    ) -> AddResult:
        """Upload a file for async processing.

        Files up to 50MB. Returns immediately with pipeline_id.

        Args:
            file: File-like object, bytes, or path string.
            entity_id: Entity this file belongs to.
            content_type: MIME type hint (auto-detected if omitted).
            title: Optional file title.

        Returns:
            AddResult with pipeline_id for status tracking.
        """
        client = await self._get_client()

        # Resolve file to (filename, content, content_type)
        if isinstance(file, str):
            path = Path(file)
            file_content = path.read_bytes()
            filename = title or path.name
        elif isinstance(file, bytes):
            file_content = file
            filename = title or "upload"
        else:
            file_content = file.read()
            filename = title or getattr(file, "name", "upload")

        files = {"file": (filename, file_content, content_type or "application/octet-stream")}
        data = {"entity_id": entity_id}
        if title:
            data["title"] = title

        # Temporarily remove JSON content-type for multipart upload
        upload_headers = {k: v for k, v in self._headers.items() if k != "Content-Type"}
        upload_client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=upload_headers,
            timeout=120.0,
        )

        try:
            response = await upload_client.post(f"/{self.api_version}/upload", files=files, data=data)
            response.raise_for_status()
            resp_data = response.json()["data"]
            return AddResult(
                memory_ids=[],
                pipeline_status=resp_data.get("pipeline_status", "queued"),
                pipeline_id=resp_data.get("pipeline_id"),
            )
        finally:
            await upload_client.aclose()

    # ---- Utility methods ----

    async def health(self) -> HealthStatus:
        """Check API health."""
        client = await self._get_client()
        response = await client.get(f"/{self.api_version}/health")
        response.raise_for_status()
        data = response.json()
        return HealthStatus(
            status=data["status"],
            version=data.get("version", ""),
            checks=data.get("checks", {}),
        )

    async def pipeline_status(self, pipeline_id: str) -> PipelineStatus:
        """Check async pipeline processing status."""
        client = await self._get_client()
        response = await client.get(f"/{self.api_version}/pipelines/{pipeline_id}")
        response.raise_for_status()
        data = response.json()["data"]
        return PipelineStatus(
            pipeline_id=data["pipeline_id"],
            status=data["status"],
            stage=data.get("stage", ""),
            document_id=data.get("document_id"),
            content_type=data.get("content_type", ""),
            chunk_count=data.get("chunk_count", 0),
            error_message=data.get("error_message"),
        )

    async def get_memory(self, memory_id: str) -> dict:
        """Get a single memory by ID."""
        client = await self._get_client()
        response = await client.get(f"/{self.api_version}/memories/{memory_id}")
        response.raise_for_status()
        return response.json()["data"]
