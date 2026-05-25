"""Processing pipeline — extraction, chunking, embedding, indexing."""

from emerald.pipeline.chunking.base import BaseChunker, Chunk
from emerald.pipeline.chunking.registry import ChunkerRegistry
from emerald.pipeline.extraction.base import BaseExtractor, ExtractedContent
from emerald.pipeline.extraction.registry import ExtractorRegistry
from emerald.pipeline.orchestrator import PipelineOrchestrator

__all__ = [
    "PipelineOrchestrator",
    "BaseExtractor", "ExtractedContent", "ExtractorRegistry",
    "BaseChunker", "Chunk", "ChunkerRegistry",
]
