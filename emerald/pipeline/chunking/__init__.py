"""Pipeline chunking subpackage."""

from emerald.pipeline.chunking.base import BaseChunker, Chunk
from emerald.pipeline.chunking.registry import ChunkerRegistry


def get_default_registry() -> ChunkerRegistry:
    """Return a pre-populated chunker registry with all built-in chunkers."""
    from emerald.pipeline.chunking.code import CodeChunker
    from emerald.pipeline.chunking.conversation import ConversationChunker
    from emerald.pipeline.chunking.markdown import MarkdownChunker
    from emerald.pipeline.chunking.pdf import PDFChunker
    from emerald.pipeline.chunking.text import TextChunker

    registry = ChunkerRegistry()
    registry.register("text", TextChunker())
    registry.register("code", CodeChunker())
    registry.register("markdown", MarkdownChunker())
    registry.register("pdf", PDFChunker())
    registry.register("conversation", ConversationChunker())
    return registry


__all__ = ["BaseChunker", "Chunk", "ChunkerRegistry", "get_default_registry"]
