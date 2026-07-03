"""Common API schemas — error responses, pagination, metadata.

v2 error format (standardized):
    {"error_code": "...", "message": "...", "details": [...], "request_id": "..."}

v1 error format (backward compatible):
    {"error": {"code": "...", "message": "..."}, "meta": {"request_id": "...", "took_ms": 0}}
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── v2 schemas (primary) ──────────────────────────────────────────────


class ErrorDetail(BaseModel):
    """A single validation error detail (v2 format)."""
    field: str | None = Field(default=None, description="Field that failed validation")
    message: str = Field(..., description="Human-readable error description")
    code: str | None = Field(default=None, description="Field-level error code")


class ApiErrorResponse(BaseModel):
    """Standardized error response for all v2 API errors.

    Returned as the response body for any non-2xx response.
    """
    error_code: str = Field(
        ...,
        description="Machine-readable error code (e.g. MEMORY_NOT_FOUND)",
        examples=["MEMORY_NOT_FOUND"],
    )
    message: str = Field(
        ...,
        description="Human-readable error description",
        examples=["The requested memory does not exist or has been deleted"],
    )
    details: list[ErrorDetail] = Field(
        default_factory=list,
        description="Additional error details (validation errors, etc.)",
    )
    request_id: str = Field(
        default="",
        description="Request ID for tracing in logs",
    )

    model_config = {"json_schema_extra": {
        "example": {
            "error_code": "MEMORY_NOT_FOUND",
            "message": "The requested memory does not exist or has been deleted",
            "details": [],
            "request_id": "a1b2c3d4",
        }
    }}


class PaginationMeta(BaseModel):
    """Cursor-based pagination metadata (v2)."""
    next_page_token: str | None = Field(
        default=None,
        description="Token for the next page. null if this is the last page.",
    )
    has_more: bool = Field(
        default=False,
        description="Whether there are more results beyond this page.",
    )
    total_count: int | None = Field(
        default=None,
        description="Total number of results (when available, may be null for search).",
    )


# ── v1 schemas (backward compatible aliases) ──────────────────────────


class _V1ErrorDetail(BaseModel):
    """v1 error detail for backward compatibility."""
    code: str = Field(examples=["INVALID_CONTENT_TYPE"])
    message: str = Field(examples=["Unsupported content type"])


class MetaResponse(BaseModel):
    """v1 response metadata."""
    request_id: str = Field(default="", examples=["req_abc123"])
    took_ms: int = Field(default=0, examples=[45])


class ErrorResponse(BaseModel):
    """v1 error response format (backward compatible).

    New code should use ``ApiErrorResponse`` (v2 format).
    """
    error: _V1ErrorDetail
    meta: MetaResponse = Field(default_factory=MetaResponse)
