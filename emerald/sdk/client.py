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
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

import httpx

from emerald.sdk.exceptions import (
    EmeraldNetworkError,
    EmeraldRateLimitError,
    EmeraldValidationError,
    exception_for_status,
)
from emerald.sdk.models import (
    AddResult,
    HealthStatus,
    PipelineStatus,
    Profile,
    ProfileFact,
    SearchResult,
    SearchResults,
)

# ---------- response parsing (I3 refactor) ----------


def _extract_error_message(body: Any, response: httpx.Response) -> str:
    """Best human-readable error message from a response body.

    Supports both v2 format (``message`` at top level) and v1 format
    (``error.message`` nested).
    """
    if isinstance(body, dict):
        # v2 format: {"error_code": "...", "message": "..."}
        msg = body.get("message")
        if msg:
            return str(msg)
        # v1 format: {"error": {"code": "...", "message": "..."}}
        err = body.get("error")
        if isinstance(err, dict):
            msg_v1 = err.get("message")
            if msg_v1:
                return str(msg_v1)
    return response.text or f"HTTP {response.status_code}"


def _extract_error_code(body: Any) -> str | None:
    """Extract the ``error_code`` field from v2 error responses."""
    if isinstance(body, dict):
        return body.get("error_code")
    return None


def _extract_retry_after(response: httpx.Response) -> int | None:
    """Parse the ``Retry-After`` header.  Returns None if missing or unparseable."""
    raw = response.headers.get("Retry-After") or response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _extract_field_errors(body: Any) -> dict[str, str] | None:
    """Pull field-level error details from the response body when present.

    Supports v2 format (``details`` as list of {field, message}) and
    v1 format (``error.details.field_errors`` as dict).
    """
    if not isinstance(body, dict):
        return None

    # v2 format: {"details": [{"field": "...", "message": "..."}, ...]}
    details = body.get("details")
    if isinstance(details, list):
        result: dict[str, str] = {}
        for d in details:
            if isinstance(d, dict):
                field = d.get("field")
                msg = d.get("message")
                if field and msg:
                    result[str(field)] = str(msg)
        if result:
            return result

    # v1 format: {"error": {"details": {"field_errors": {...}}}}
    err = body.get("error")
    if not isinstance(err, dict):
        return None
    nested = err.get("details")
    if not isinstance(nested, dict):
        return None
    fe = nested.get("field_errors")
    if not isinstance(fe, dict):
        return None
    return {str(k): str(v) for k, v in fe.items()}


def _raise_for_status(response: httpx.Response) -> None:
    """Map an HTTP error response to a typed SDK exception.

    Replaces raw ``response.raise_for_status()`` so callers can catch
    ``EmeraldAuthError`` / ``EmeraldNotFoundError`` etc. (per sdk-guide.md).
    """
    if response.is_success:
        return
    try:
        body = response.json()
    except Exception:
        body = None

    msg = _extract_error_message(body, response)
    error_code = _extract_error_code(body)
    retry_after = _extract_retry_after(response)
    field_errors = _extract_field_errors(body)

    exc = exception_for_status(
        response.status_code, msg, error_code=error_code, response=response,
    )
    if isinstance(exc, EmeraldRateLimitError) and retry_after is not None:
        exc.retry_after = retry_after
    if isinstance(exc, EmeraldValidationError) and field_errors:
        exc.field_errors = field_errors
    raise exc


class EmeraldClient:
    """Async client for the Emerald memory API.

    Usage:
        client = EmeraldClient(api_key="em_xxx")
        result = await client.add("用户喜欢 TypeScript", entity_id="user_123")
        profile = await client.profile("user_123")
        results = await client.search("TypeScript", entity_id="user_123")

    Or as an async context manager (auto-closes on exit):
        async with EmeraldClient(api_key="em_xxx") as client:
            ...

    Errors are surfaced as typed exceptions — see ``emerald.sdk.exceptions``.
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

    async def __aenter__(self) -> EmeraldClient:
        """Enter the async context: returns the client itself.

        Use as ``async with EmeraldClient(...) as client:``.  The underlying
        httpx client is created lazily on first use; ``__aexit__`` calls
        ``close()`` so connections are released.
        """
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Exit the async context: closes the underlying httpx client.

        Always runs (even on exception) so callers don't leak connections.
        """
        await self.close()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self._headers,
                timeout=30.0,
            )
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        files: Any | None = None,
        data: Any | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """Issue an HTTP request and translate network/HTTP errors to typed SDK exceptions.

        - ``httpx.TransportError`` → ``EmeraldNetworkError`` (connect timeout, DNS, etc.)
        - non-2xx response → typed exception via ``_raise_for_status``
        - 2xx response → returned unchanged for the caller to parse

        The shared httpx client carries the base URL and default headers
        (Authorization, Content-Type).  Per-request ``headers`` and
        ``timeout`` are layered on top — useful for multipart upload which
        must NOT send ``Content-Type: application/json`` and may need a
        longer read timeout.
        """
        client = await self._get_client()
        try:
            response = await client.request(
                method, path,
                json=json, files=files, data=data,
                headers=headers, timeout=timeout,
            )
        except httpx.TransportError as exc:
            raise EmeraldNetworkError(
                f"Network error contacting Emerald API: {exc}",
            ) from exc
        _raise_for_status(response)
        return response

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
        content_type: str | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
        require_confirmation_for_high_impact: bool = False,
        memory_type: str | None = None,
        confidence: float | None = None,
        valid_until: datetime | None = None,
    ) -> AddResult:
        """Add content to the memory graph.

        Args:
            content: Text content to ingest.
            entity_id: Entity (user, project, org) this content belongs to.
            content_type: Content type hint (auto-detected when omitted:
                JSON/CSV content is sniffed and chunked structurally).
            title: Optional content title.
            metadata: Optional key-value metadata.
            require_confirmation_for_high_impact: Flag high-impact contradictions
                for confirmation instead of auto-resolving.
            memory_type: Optional override for the LLM-extracted memory type.
                One of 'fact', 'preference', or 'episodic'. When set, takes
                precedence over both the chunker default and ``metadata``.
                **Passing None leaves the lower priority (``metadata`` then
                chunker default) to decide.**
            confidence: Optional override for the LLM-assigned confidence
                score (0.0-1.0).  When set, the engine skips re-scoring.
                **Passing None defers to lower-priority values.**
            valid_until: Optional expiry datetime (UTC or timezone-aware).
                After this point, the ForgetEngine will mark the memory
                ``is_latest=False``. **None means "use the lower priority,
                which may itself be None for no expiry".**

        Returns:
            AddResult with memory IDs, pipeline status, and any pending conflicts.
        """
        body: dict[str, Any] = {
            "content": content,
            "entity_id": entity_id,
            "require_confirmation_for_high_impact": require_confirmation_for_high_impact,
        }
        if content_type is not None:
            body["content_type"] = content_type
        if title:
            body["title"] = title
        if metadata:
            body["metadata"] = metadata
        if memory_type is not None:
            body["memory_type"] = memory_type
        if confidence is not None:
            body["confidence"] = confidence
        if valid_until is not None:
            # Pydantic will accept either datetime or ISO string; sending
            # ISO 8601 keeps the wire format stable and timezone-explicit.
            body["valid_until"] = valid_until.isoformat()

        response = await self._request("POST", f"/{self.api_version}/memories", json=body)
        data = response.json()["data"]
        return AddResult(
            memory_ids=data["memory_ids"],
            pipeline_status=data.get("pipeline_status", "done"),
            extracted_count=data.get("extracted_count", 0),
            pipeline_id=data.get("pipeline_id"),
            conflicts_pending=data.get("conflicts_pending", []),
        )

    async def search(
        self,
        q: str,
        *,
        entity_id: str,
        search_mode: str = "hybrid",
        top_k: int = 30,
        rerank: bool = False,
        rewrite_query: bool = False,
        filters: dict[str, Any] | None = None,
        min_confidence: float | None = None,
        dynamic_truncation: bool = True,
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
            min_confidence: Minimum memory confidence (0-1).
            dynamic_truncation: Stop returning results when score gap exceeds threshold.

        Returns:
            SearchResults with scored, deduplicated hits.
        """
        body: dict[str, Any] = {
            "q": q,
            "entity_id": entity_id,
            "search_mode": search_mode,
            "top_k": top_k,
            "rerank": rerank,
            "rewrite_query": rewrite_query,
            "dynamic_truncation": dynamic_truncation,
        }
        if filters:
            body["filters"] = filters
        if min_confidence is not None:
            body["min_confidence"] = min_confidence

        response = await self._request("POST", f"/{self.api_version}/search", json=body)
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
        response = await self._request("GET", f"/{self.api_version}/profiles/{entity_id}")
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

        # I2: use the shared httpx client.  Override the default
        # ``Content-Type: application/json`` header for this one request —
        # httpx will auto-set the multipart boundary instead.  And extend
        # the timeout to 120s (large files take longer to upload).
        headers = {k: v for k, v in self._headers.items() if k != "Content-Type"}
        response = await self._request(
            "POST", f"/{self.api_version}/upload",
            files=files, data=data,
            headers=headers, timeout=120.0,
        )
        resp_data = response.json()["data"]
        return AddResult(
            memory_ids=[],
            pipeline_status=resp_data.get("pipeline_status", "queued"),
            pipeline_id=resp_data.get("pipeline_id"),
        )

    # ---- Utility methods ----

    async def health(self) -> HealthStatus:
        """Check API health."""
        response = await self._request("GET", f"/{self.api_version}/health")
        data = response.json()
        return HealthStatus(
            status=data["status"],
            version=data.get("version", ""),
            checks=data.get("checks", {}),
        )

    async def pipeline_status(self, pipeline_id: str) -> PipelineStatus:
        """Check async pipeline processing status."""
        response = await self._request("GET", f"/{self.api_version}/pipelines/{pipeline_id}")
        data = response.json()["data"]
        return PipelineStatus(
            pipeline_id=data["pipeline_id"],
            status=data["status"],
            stage=data.get("stage", ""),
            document_id=data.get("document_id"),
            content_type=data.get("content_type", ""),
            error_message=data.get("error_message"),
            fact_extraction_status=data.get("fact_extraction_status"),
            memory_count=data.get("memory_count", 0),
        )

    async def get_memory(self, memory_id: str) -> dict:
        """Get a single memory by ID."""
        response = await self._request("GET", f"/{self.api_version}/memories/{memory_id}")
        return response.json()["data"]
