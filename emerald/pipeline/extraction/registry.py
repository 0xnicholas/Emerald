"""Extractor registry — maps content types to extractor instances."""

from __future__ import annotations

import structlog

from emerald.pipeline.extraction.base import BaseExtractor, ExtractedContent

logger = structlog.get_logger(__name__)


class ExtractorRegistry:
    """Registry of content extractors, keyed by content type string."""

    def __init__(self) -> None:
        self._extractors: dict[str, BaseExtractor] = {}

    def register(self, content_type: str, extractor: BaseExtractor) -> None:
        self._extractors[content_type] = extractor
        logger.debug("extractor.registered", content_type=content_type)

    def get(self, content_type: str) -> BaseExtractor:
        if content_type not in self._extractors:
            raise UnsupportedContentType(
                f"No extractor for content_type='{content_type}'. "
                f"Available: {list(self._extractors)}"
            )
        return self._extractors[content_type]

    async def run(
        self, content: str | bytes, content_type: str = "text", **kwargs
    ) -> ExtractedContent:
        """Run extraction using the appropriate registered extractor."""
        return await self.extract(content, content_type, **kwargs)

    async def extract(
        self, content: str | bytes, content_type: str = "text", **kwargs
    ) -> ExtractedContent:
        """Extract content (alias for run)."""
        extractor = self.get(content_type)
        logger.info("extraction.start", content_type=content_type)
        try:
            result = await extractor.extract(content, **kwargs)
            logger.info(
                "extraction.done",
                content_type=content_type,
                text_length=len(result.text),
            )
            return result
        except Exception as e:
            logger.error(
                "extraction.failed",
                content_type=content_type,
                error=str(e),
            )
            raise


class UnsupportedContentType(Exception):
    """Raised when no extractor exists for a content type."""
