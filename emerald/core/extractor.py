"""Extraction engine — re-exports from the pipeline extraction subpackage.

The single source of truth for extractors lives in emerald.pipeline.extraction.
"""

from emerald.pipeline.extraction.base import BaseExtractor, ExtractedContent
from emerald.pipeline.extraction.registry import ExtractorRegistry, UnsupportedContentType

__all__ = [
    "BaseExtractor",
    "ExtractedContent",
    "ExtractorRegistry",
    "UnsupportedContentType",
]
