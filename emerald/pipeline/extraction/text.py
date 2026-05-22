"""Text extractor — direct pass-through with basic cleaning."""

from __future__ import annotations

from emerald.core.exceptions import EmptyContentError
from emerald.pipeline.extraction.base import BaseExtractor, ExtractedContent


class TextExtractor(BaseExtractor):
    """Simple pass-through extractor for plain text. Strips and validates."""

    async def extract(self, content: str, **kwargs) -> ExtractedContent:
        text = content.strip()
        if not text:
            raise EmptyContentError()
        return ExtractedContent(text=text, content_type="text")

    def supports(self, content_type: str) -> bool:
        return content_type == "text"
