"""Pipeline extraction subpackage."""

from emerald.pipeline.extraction.base import BaseExtractor, ExtractedContent
from emerald.pipeline.extraction.registry import ExtractorRegistry


def get_default_registry() -> ExtractorRegistry:
    """Return a pre-populated extractor registry with all built-in extractors."""
    from emerald.pipeline.extraction.audio import AudioExtractor
    from emerald.pipeline.extraction.code import CodeExtractor
    from emerald.pipeline.extraction.image import ImageExtractor
    from emerald.pipeline.extraction.pdf import PDFExtractor
    from emerald.pipeline.extraction.text import TextExtractor
    from emerald.pipeline.extraction.url import URLExtractor
    from emerald.pipeline.extraction.video import VideoExtractor

    registry = ExtractorRegistry()
    registry.register("text", TextExtractor())
    registry.register("code", CodeExtractor())
    registry.register("pdf", PDFExtractor())
    registry.register("url", URLExtractor())
    registry.register("image", ImageExtractor())
    registry.register("audio", AudioExtractor())
    registry.register("video", VideoExtractor())
    # Structured data (JSON/CSV) is plain text — handled by the text extractor.
    registry.register("json", TextExtractor())
    registry.register("csv", TextExtractor())
    return registry


__all__ = ["BaseExtractor", "ExtractedContent", "ExtractorRegistry", "get_default_registry"]
