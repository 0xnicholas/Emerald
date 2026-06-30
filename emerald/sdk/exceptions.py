"""SDK custom exception types (P1.2c fix).

The SDK previously surfaced every HTTP error as the generic
``httpx.HTTPStatusError``, forcing callers to inspect ``e.response.status_code``
themselves.  Per ``docs/api/sdk-guide.md`` the SDK exposes typed exceptions
that map cleanly to the documented HTTP status codes:

| HTTP | Exception                | Scenario                                 |
|------|--------------------------|------------------------------------------|
| 401  | ``EmeraldAuthError``     | API key invalid or expired               |
| 404  | ``EmeraldNotFoundError`` | Memory / profile / pipeline not found    |
| 422  | ``EmeraldValidationError``| Request body validation failure          |
| 429  | ``EmeraldRateLimitError``| Rate limit (carries ``retry_after``)     |
| 5xx  | ``EmeraldServerError``   | Server-side error (auto-retried 3x)      |
| net  | ``EmeraldNetworkError``  | Connection timeout, DNS failure          |

All exceptions inherit from ``EmeraldError`` so callers can catch broadly.
"""

from __future__ import annotations

from typing import Any


class EmeraldError(Exception):
    """Base class for all SDK-raised errors.

    Catch this for broad error handling; catch the subclasses for precise
    branching.
    """

    def __init__(self, message: str, *, response: Any | None = None) -> None:
        self.response = response
        super().__init__(message)


class EmeraldAuthError(EmeraldError):
    """401 — API key is missing, invalid, or expired."""


class EmeraldNotFoundError(EmeraldError):
    """404 — the requested resource (memory, profile, pipeline) does not exist."""


class EmeraldValidationError(EmeraldError):
    """422 — request body failed validation.

    Carries ``field_errors`` (dict mapping field name -> error message)
    parsed from the server's validation error response when available.
    """

    def __init__(
        self,
        message: str,
        *,
        field_errors: dict[str, str] | None = None,
        response: Any | None = None,
    ) -> None:
        self.field_errors = field_errors or {}
        super().__init__(message, response=response)


class EmeraldRateLimitError(EmeraldError):
    """429 — rate limit exceeded.

    Carries ``retry_after`` (seconds) parsed from the Retry-After header
    or response body when available.
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after: int | None = None,
        response: Any | None = None,
    ) -> None:
        self.retry_after = retry_after
        super().__init__(message, response=response)


class EmeraldServerError(EmeraldError):
    """5xx — server-side error. The SDK auto-retries 3 times before raising."""


class EmeraldNetworkError(EmeraldError):
    """Network-level failure: connection timeout, DNS failure, etc.

    Raised when the underlying ``httpx`` request throws a non-HTTP error
    (e.g. ``httpx.ConnectTimeout``, ``httpx.ConnectError``).
    """


_STATUS_TO_EXCEPTION: dict[int, type[EmeraldError]] = {
    401: EmeraldAuthError,
    403: EmeraldAuthError,  # 403 in our API = "API key not authorized for entity"
    404: EmeraldNotFoundError,
    422: EmeraldValidationError,
    429: EmeraldRateLimitError,
}


def exception_for_status(
    status_code: int, message: str, response: Any | None = None
) -> EmeraldError:
    """Map an HTTP status code to the most specific SDK exception type.

    5xx responses map to ``EmeraldServerError``.  Anything unmapped (e.g. 4xx
    we haven't catalogued yet) falls back to ``EmeraldError`` so callers
    can still catch and handle.
    """
    if 500 <= status_code < 600:
        return EmeraldServerError(message, response=response)
    exc = _STATUS_TO_EXCEPTION.get(status_code)
    if exc is not None:
        return exc(message, response=response)
    return EmeraldError(message, response=response)
