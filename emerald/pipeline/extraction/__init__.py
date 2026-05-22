"""Pipeline extraction subpackage."""

from emerald.pipeline.extraction.base import BaseExtractor, ExtractedContent
from emerald.pipeline.extraction.registry import ExtractorRegistry

__all__ = ["BaseExtractor", "ExtractedContent", "ExtractorRegistry"]
