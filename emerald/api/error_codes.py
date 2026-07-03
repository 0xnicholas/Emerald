"""Emerald business error code registry (v2).

Standardized machine-readable error codes for every failure mode.
Each code maps to an HTTP status and a human-readable description.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ErrorCategory(str, Enum):
    """Broad error categories for client-side routing."""
    AUTH = "auth"
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    RATE_LIMIT = "rate_limit"
    SERVER = "server"
    CONNECTOR = "connector"


@dataclass(frozen=True)
class ErrorCode:
    """A single business error code."""
    code: str           # e.g. "MEMORY_NOT_FOUND"
    http_status: int    # e.g. 404
    category: ErrorCategory
    description: str    # Human-readable for docs


# Registry of all business error codes
_ERROR_CODES: dict[str, ErrorCode] = {}


def _register(code: str, http_status: int, category: ErrorCategory, description: str) -> ErrorCode:
    ec = ErrorCode(code=code, http_status=http_status, category=category, description=description)
    _ERROR_CODES[code] = ec
    return ec


# -- Auth errors (401/403) --
AUTH_INVALID_KEY = _register("AUTH_INVALID_KEY", 401, ErrorCategory.AUTH,
    "API key is missing, invalid, or expired")
AUTH_INSUFFICIENT_PERMISSIONS = _register("AUTH_INSUFFICIENT_PERMISSIONS", 403, ErrorCategory.AUTH,
    "API key lacks required permissions for this operation")
ENTITY_UNAUTHORIZED = _register("ENTITY_UNAUTHORIZED", 403, ErrorCategory.AUTH,
    "API key is not authorized for the requested entity")

# -- Validation errors (422) --
VALIDATION_ERROR = _register("VALIDATION_ERROR", 422, ErrorCategory.VALIDATION,
    "Request body or parameters failed validation")
INVALID_CONTENT_TYPE = _register("INVALID_CONTENT_TYPE", 422, ErrorCategory.VALIDATION,
    "The provided content type is not supported")
CONTENT_TOO_LARGE = _register("CONTENT_TOO_LARGE", 422, ErrorCategory.VALIDATION,
    "Uploaded content exceeds the size limit")
INVALID_PAGINATION_TOKEN = _register("INVALID_PAGINATION_TOKEN", 422, ErrorCategory.VALIDATION,
    "The provided page_token is invalid or expired")

# -- Not found errors (404) --
MEMORY_NOT_FOUND = _register("MEMORY_NOT_FOUND", 404, ErrorCategory.NOT_FOUND,
    "The requested memory does not exist or has been deleted")
PROFILE_NOT_FOUND = _register("PROFILE_NOT_FOUND", 404, ErrorCategory.NOT_FOUND,
    "The requested profile does not exist")
PIPELINE_NOT_FOUND = _register("PIPELINE_NOT_FOUND", 404, ErrorCategory.NOT_FOUND,
    "The requested pipeline job does not exist")
SESSION_NOT_FOUND = _register("SESSION_NOT_FOUND", 404, ErrorCategory.NOT_FOUND,
    "The requested session does not exist or has expired")
ROUTE_NOT_FOUND = _register("ROUTE_NOT_FOUND", 404, ErrorCategory.NOT_FOUND,
    "The requested API route does not exist")
FILE_NOT_FOUND = _register("FILE_NOT_FOUND", 404, ErrorCategory.NOT_FOUND,
    "The requested file was not found in storage")

# -- Conflict errors (409) --
MEMORY_ALREADY_EXISTS = _register("MEMORY_ALREADY_EXISTS", 409, ErrorCategory.CONFLICT,
    "A memory with the same custom_id already exists")
DUPLICATE_RESOURCE = _register("DUPLICATE_RESOURCE", 409, ErrorCategory.CONFLICT,
    "A resource with the same identifier already exists")

# -- Rate limit errors (429) --
RATE_LIMITED = _register("RATE_LIMITED", 429, ErrorCategory.RATE_LIMIT,
    "Too many requests. Retry after the indicated delay.")

# -- Server errors (500/502/503) --
INTERNAL_ERROR = _register("INTERNAL_ERROR", 500, ErrorCategory.SERVER,
    "An unexpected internal error occurred")
SERVICE_UNAVAILABLE = _register("SERVICE_UNAVAILABLE", 503, ErrorCategory.SERVER,
    "A dependent service (database, Redis, etc.) is temporarily unavailable")
PIPELINE_FAILED = _register("PIPELINE_FAILED", 500, ErrorCategory.SERVER,
    "A pipeline stage failed during processing")
EXTRACTION_FAILED = _register("EXTRACTION_FAILED", 500, ErrorCategory.SERVER,
    "Content extraction failed")
EMBEDDING_FAILED = _register("EMBEDDING_FAILED", 500, ErrorCategory.SERVER,
    "Embedding generation failed")

# -- Internal exception name → error code mappings (Fix #7) --
# These map Python exception class names (uppercased) to error codes so
# the emerald_error_handler returns the correct HTTP status instead of
# always defaulting to 400.
_INTERNAL_EXCEPTION_MAP: dict[str, str] = {
    "NOTFOUNDERROR": "MEMORY_NOT_FOUND",
    "AUTHENTICATIONERROR": "AUTH_INVALID_KEY",
    "PERMISSIONDENIEDERROR": "AUTH_INSUFFICIENT_PERMISSIONS",
    "DUPLICATEERROR": "DUPLICATE_RESOURCE",
    "UNSUPPORTEDCONTENTTYPEERROR": "INVALID_CONTENT_TYPE",
    "CONTENTTOOLARGEERROR": "CONTENT_TOO_LARGE",
    "EXTRACTIONERROR": "EXTRACTION_FAILED",
    "CHUNKINGERROR": "PIPELINE_FAILED",
    "EMBEDDINGERROR": "EMBEDDING_FAILED",
    "INDEXINGERROR": "PIPELINE_FAILED",
    "CONNECTORERROR": "CONNECTOR_AUTH_FAILED",
    "UNSUPPORTEDCONNECTORERROR": "CONNECTOR_NOT_SUPPORTED",
    "CONNECTORAUTHERROR": "CONNECTOR_AUTH_FAILED",
}

# -- Connector errors (502) --
CONNECTOR_AUTH_FAILED = _register("CONNECTOR_AUTH_FAILED", 502, ErrorCategory.CONNECTOR,
    "OAuth authentication with external provider failed")
CONNECTOR_WEBHOOK_INVALID = _register("CONNECTOR_WEBHOOK_INVALID", 400, ErrorCategory.CONNECTOR,
    "Received invalid webhook payload from connector")
CONNECTOR_NOT_SUPPORTED = _register("CONNECTOR_NOT_SUPPORTED", 400, ErrorCategory.CONNECTOR,
    "The requested connector provider is not supported")


def get_error_code(code: str) -> ErrorCode:
    """Look up an error code.

    Checks the internal exception class name mapping first (Fix #7),
    then the error code registry. Returns INTERNAL_ERROR for unknown codes.
    """
    # Check internal exception name → error code mapping first
    mapped = _INTERNAL_EXCEPTION_MAP.get(code.upper())
    if mapped and mapped in _ERROR_CODES:
        return _ERROR_CODES[mapped]
    return _ERROR_CODES.get(code, INTERNAL_ERROR)


def list_error_codes() -> list[ErrorCode]:
    """Return all registered error codes (for documentation)."""
    return sorted(_ERROR_CODES.values(), key=lambda e: (e.http_status, e.code))
