"""URL metadata extraction — POST /v1/extract-url."""

from __future__ import annotations

import logging
import re
import time
import uuid
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from emerald.api.dependencies import api_key_auth, rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Extract"])


class ExtractUrlRequest(BaseModel):
    url: str = Field(examples=["https://example.com/article"])


class ExtractUrlResponse(BaseModel):
    url: str
    title: str = ""
    description: str = ""
    favicon: str = ""
    image: str = ""
    site_name: str = ""


def _extract_meta(html: str, url: str) -> dict[str, str]:
    """Extract metadata from HTML using regex patterns."""
    result = {
        "url": url,
        "title": "",
        "description": "",
        "favicon": "",
        "image": "",
        "site_name": "",
    }

    # Title: <title> or og:title
    m = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE | re.DOTALL)
    if m:
        result["title"] = m.group(1).strip()
    m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if m:
        result["title"] = m.group(1).strip()

    # Description: meta description or og:description
    m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if m:
        result["description"] = m.group(1).strip()
    m = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if m:
        result["description"] = m.group(1).strip()

    # Image: og:image
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if m:
        result["image"] = m.group(1).strip()

    # Site name: og:site_name
    m = re.search(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if m:
        result["site_name"] = m.group(1).strip()

    # Favicon
    m = re.search(r'<link[^>]+rel=["\'](?:shortcut )?icon["\'][^>]+href=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if m:
        fav = m.group(1).strip()
        if fav.startswith("//"):
            fav = "https:" + fav
        elif fav.startswith("/"):
            parsed = urlparse(url)
            fav = f"{parsed.scheme}://{parsed.netloc}{fav}"
        result["favicon"] = fav

    return result


@router.post(
    "/extract-url",
    dependencies=[Depends(api_key_auth), Depends(rate_limit)],
)
async def extract_url(body: ExtractUrlRequest, request: Request) -> dict:
    """Extract title, description, favicon from a URL.

    Authenticated and rate-limited: the endpoint performs an outbound
    HTTP fetch, so without auth it is an unauthenticated SSRF/resource-
    abuse surface (audit finding 2026-08-10, fixed).
    """
    start = time.perf_counter()
    request_id = getattr(request.state, "request_id", str(uuid.uuid4())[:8])

    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; EmeraldBot/1.0)",
                "Accept": "text/html,application/xhtml+xml",
            })
            resp.raise_for_status()
            html = resp.text
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="URL fetch timed out")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch URL: {e}")

    data = _extract_meta(html, url)

    return {
        "data": data,
        "meta": {
            "request_id": request_id,
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }
