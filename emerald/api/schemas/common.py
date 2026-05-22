"""Common API schemas — error responses, pagination, metadata."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MetaResponse(BaseModel):
    request_id: str = Field(default="", examples=["req_abc123"])
    took_ms: int = Field(default=0, examples=[45])


class ErrorDetail(BaseModel):
    code: str = Field(examples=["INVALID_CONTENT_TYPE"])
    message: str = Field(examples=["Unsupported content type"])
    details: dict | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
    meta: MetaResponse = Field(default_factory=MetaResponse)


class PaginationMeta(BaseModel):
    total: int
    page: int
    page_size: int
    next_cursor: str | None = None
