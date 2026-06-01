"""Extraction engine — re-exports from the pipeline extraction subpackage.

The single source of truth for extractors lives in emerald.pipeline.extraction.
"""

from emerald.pipeline.extraction.base import BaseExtractor, ExtractedContent
from emerald.pipeline.extraction.registry import ExtractorRegistry, UnsupportedContentType
from emerald.pipeline.extraction import get_default_registry

__all__ = [
    "BaseExtractor",
    "ExtractedContent",
    "ExtractorRegistry",
    "UnsupportedContentType",
    "get_default_registry",
]
