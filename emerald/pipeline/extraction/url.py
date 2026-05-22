"""URL extractor — fetch and clean web pages."""

from __future__ import annotations

import re

from emerald.core.exceptions import ExtractionError
from emerald.pipeline.extraction.base import BaseExtractor, ExtractedContent

_URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)


class URLExtractor(BaseExtractor):
    """Fetches a URL, strips HTML boilerplate, returns clean text.

    Uses trafilatura for main content extraction when available.
    Falls back to basic HTML cleaning for environments without it.
    """

    async def extract(self, content: str, **kwargs) -> ExtractedContent:
        url = content.strip()

        if not self._is_valid_url(url):
            raise ExtractionError(
                content_type="url",
                reason=f"Invalid URL format: {url}",
                retryable=False,
            )

        # Try trafilatura first
        try:
            import trafilatura

            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                text = trafilatura.extract(
                    downloaded,
                    include_comments=False,
                    include_tables=True,
                    no_fallback=False,
                )
                if text:
                    return ExtractedContent(
                        text=text.strip(),
                        content_type="url",
                        metadata={"source_url": url},
                    )
        except ImportError:
            pass
        except Exception as e:
            raise ExtractionError(
                content_type="url",
                reason=f"Failed to fetch URL: {e}",
                retryable=True,
            )

        # Fallback: basic HTTP get
        try:
            import urllib.request

            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Emerald/0.1"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8", errors="replace")
                text = self._strip_html(html)
                return ExtractedContent(
                    text=text.strip(),
                    content_type="url",
                    metadata={"source_url": url},
                )
        except Exception as e:
            raise ExtractionError(
                content_type="url",
                reason=f"Failed to fetch URL: {e}",
                retryable=True,
            )

    def supports(self, content_type: str) -> bool:
        return content_type == "url"

    @staticmethod
    def _is_valid_url(url: str) -> bool:
        return bool(_URL_RE.match(url))

    @staticmethod
    def _strip_html(html: str) -> str:
        """Basic HTML tag stripping (fallback when trafilatura unavailable)."""
        # Remove script and style blocks
        html = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
        html = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
        # Remove all HTML tags
        html = re.sub(r"<[^>]+>", " ", html)
        # Collapse whitespace
        html = re.sub(r"\s+", " ", html)
        return html.strip()
