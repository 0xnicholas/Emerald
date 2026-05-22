"""Core business logic modules."""

from emerald.core.engine import MemoryEngine
from emerald.core.extractor import ExtractorRegistry, BaseExtractor, ExtractedContent
from emerald.core.chunker import ChunkerRegistry, BaseChunker, Chunk
from emerald.core.embedder import EmbeddingProvider, get_embedding_provider
from emerald.core.relationship import RelationshipEngine, RelationType
from emerald.core.profile import ProfileManager
from emerald.core.search import SearchOrchestrator, SearchMode
from emerald.core.forget import ForgetEngine, ForgetStrategy
from emerald.core.logging import configure_logging
from emerald.core.exceptions import (
    EmeraldError,
    ExtractionError,
    EmbeddingError,
    PipelineError,
    NotFoundError,
    UnsupportedContentTypeError,
)

__all__ = [
    "MemoryEngine",
    "ExtractorRegistry", "BaseExtractor", "ExtractedContent",
    "ChunkerRegistry", "BaseChunker", "Chunk",
    "EmbeddingProvider", "get_embedding_provider",
    "RelationshipEngine", "RelationType",
    "ProfileManager",
    "SearchOrchestrator", "SearchMode",
    "ForgetEngine", "ForgetStrategy",
    # Logging + exceptions
    "configure_logging", "EmeraldError", "ExtractionError", "EmbeddingError",
    "PipelineError", "NotFoundError", "UnsupportedContentTypeError",
]
