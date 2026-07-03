"""V2 API routes.

V2 builds on V1 with the following substantive improvements:

1. **Standardized error codes** — All error responses include a machine-readable
   ``error_code`` field (e.g. ``MEMORY_NOT_FOUND``, ``RATE_LIMITED``).
   See ``emerald.api.error_codes`` for the full registry.

2. **Cursor-based pagination** — List/search endpoints accept ``page_token``
   and return ``pagination`` metadata (``next_page_token``, ``has_more``).

3. **Rate limit headers** — Every response includes ``X-RateLimit-Limit``,
   ``X-RateLimit-Remaining``, and ``X-RateLimit-Reset`` headers.

4. **idempotency_key** — ``POST /v2/memories`` supports idempotent writes via
   the ``idempotency_key`` field (prevents duplicate memories on retry).

V2 is backward-compatible with V1 for the core request/response shapes.
Breaking changes will be introduced in a future minor version.

When a breaking change is needed, replace the individual V2 re-export file
with a concrete V2 implementation instead of importing from V1.
"""
