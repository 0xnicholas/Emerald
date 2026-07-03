"""Cursor-based pagination for Emerald API.

Encodes opaque base64 tokens containing the last-seen item's sort key,
enabling stable, efficient pagination even as the collection grows.

Usage in route handlers::

    from emerald.api.pagination import PageToken, PageParams

    # Decode incoming token
    token = PageToken.decode(request.page_token)

    # Query with cursor
    results = await query(limit=token.limit + 1, after=token.cursor)

    # Encode next-page token
    if len(results) > token.limit:
        next_token = PageToken.encode(
            cursor=results[-2].id,  # last item of current page
            limit=token.limit,
        )
        results = results[:token.limit]
    else:
        next_token = None

    return {
        "data": results,
        "pagination": {
            "next_page_token": next_token,
            "has_more": next_token is not None,
        }
    }
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any


class InvalidPaginationToken(ValueError):
    """Raised when a page_token is corrupt, expired, or malformed."""


@dataclass(frozen=True)
class PageToken:
    """Decoded page token with cursor and limit."""
    cursor: str | None   # The last-seen item key (e.g. memory_id)
    limit: int            # Page size
    offset: int           # Fallback offset (when cursor is None)

    @staticmethod
    def decode(token_str: str | None, default_limit: int = 20, max_limit: int = 100) -> PageToken:
        """Decode a base64 page token string into a PageToken.

        Returns a fresh first-page token when ``token_str`` is None or empty.
        **Lenient**: invalid tokens silently return first page.  For strict
        validation (raising on corrupt tokens), use ``decode_or_raise``.
        """
        if not token_str:
            return PageToken(cursor=None, limit=default_limit, offset=0)

        try:
            payload = json.loads(
                base64.urlsafe_b64decode(token_str.encode()).decode()
            )
            cursor = payload.get("c")
            limit = min(int(payload.get("l", default_limit)), max_limit)
            offset = int(payload.get("o", 0))
            return PageToken(cursor=cursor, limit=limit, offset=offset)
        except Exception:
            # Invalid token → return first page (backward-compatible)
            return PageToken(cursor=None, limit=default_limit, offset=0)

    @staticmethod
    def decode_or_raise(token_str: str | None, default_limit: int = 20, max_limit: int = 100) -> PageToken:
        """Decode a base64 page token, raising on corrupt or invalid tokens.

        Use this in route handlers that want to surface pagination errors
        to clients (e.g. returning 422 INVALID_PAGINATION_TOKEN) instead
        of silently resetting to the first page.

        Raises:
            InvalidPaginationToken: if the token cannot be decoded.
        """
        if not token_str:
            return PageToken(cursor=None, limit=default_limit, offset=0)

        try:
            payload = json.loads(
                base64.urlsafe_b64decode(token_str.encode()).decode()
            )
            cursor = payload.get("c")
            limit = min(int(payload.get("l", default_limit)), max_limit)
            offset = int(payload.get("o", 0))
            return PageToken(cursor=cursor, limit=limit, offset=offset)
        except Exception as exc:
            raise InvalidPaginationToken(
                f"Invalid page_token: {token_str[:20]}..."
            ) from exc

    @staticmethod
    def encode(cursor: str, limit: int = 20, offset: int = 0) -> str:
        """Encode a cursor + limit + offset into a base64 page token string."""
        payload = json.dumps({"c": cursor, "l": limit, "o": offset})
        return base64.urlsafe_b64encode(payload.encode()).decode()

    @staticmethod
    def next_page(results: list[Any], current: PageToken, key_attr: str = "id") -> str | None:
        """Build the next-page token from a results list.

        If ``results`` has more items than ``current.limit``, slices to
        ``limit`` and encodes a token pointing at the last item's key.

        Returns ``None`` if there are no more pages.
        """
        if len(results) <= current.limit:
            return None

        last_item = results[current.limit - 1]
        cursor = getattr(last_item, key_attr, None)
        if cursor is None and isinstance(last_item, dict):
            cursor = last_item.get(key_attr)
        if cursor is None:
            return None

        return PageToken.encode(
            cursor=str(cursor),
            limit=current.limit,
        )

    @staticmethod
    def pagination_meta(
        results: list[Any],
        page_token: PageToken,
        key_attr: str = "id",
    ) -> dict[str, Any]:
        """Compute pagination metadata for a response.

        Returns a dict with ``next_page_token`` and ``has_more``.
        """
        if len(results) > page_token.limit:
            next_token = PageToken.next_page(results, page_token, key_attr)
            return {
                "next_page_token": next_token,
                "has_more": next_token is not None,
            }
        return {
            "next_page_token": None,
            "has_more": False,
        }
