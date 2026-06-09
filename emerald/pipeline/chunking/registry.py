"""Chunker registry — maps content types to chunker instances."""

from __future__ import annotations

import structlog

from emerald.pipeline.chunking.base import BaseChunker, Chunk

logger = structlog.get_logger(__name__)


class ChunkerRegistry:
    """Registry of chunkers, keyed by content type string."""

    def __init__(self) -> None:
        self._chunkers: dict[str, BaseChunker] = {}

    def register(self, content_type: str, chunker: BaseChunker) -> None:
        self._chunkers[content_type] = chunker
        logger.debug("chunker.registered", content_type=content_type)

    def get(self, content_type: str) -> BaseChunker:
        if content_type not in self._chunkers:
            # Fallback to text chunker if available
            if "text" in self._chunkers:
                return self._chunkers["text"]
            raise UnsupportedContentType(
                f"No chunker for content_type='{content_type}'. "
                f"Available: {list(self._chunkers)}"
            )
        return self._chunkers[content_type]

    async def run(self, text: str, content_type: str = "text", **kwargs) -> list[Chunk]:
        """Split text using the appropriate chunking strategy."""
        return await self.chunk(text, content_type, **kwargs)

    async def chunk(self, text: str, content_type: str = "text", **kwargs) -> list[Chunk]:
        """Split text (primary interface)."""
        chunker = self.get(content_type)
        logger.info(
            "chunking.start",
            content_type=content_type,
            text_length=len(text),
        )
        chunks = await chunker.chunk(text, **kwargs)
        logger.info("chunking.done", chunk_count=len(chunks))
        return chunks


class UnsupportedContentType(Exception):
    """Raised when no chunker exists for a content type."""
