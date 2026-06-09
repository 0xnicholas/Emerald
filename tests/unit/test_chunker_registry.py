"""Unit tests for ChunkerRegistry."""

import pytest

from emerald.pipeline.chunking.registry import ChunkerRegistry, UnsupportedContentType
from emerald.pipeline.chunking.text import TextChunker


@pytest.fixture
def registry():
    return ChunkerRegistry()


async def test_register_and_get(registry):
    """After registering, get() returns the chunker."""
    chunker = TextChunker()
    registry.register("text", chunker)
    assert registry.get("text") is chunker


async def test_fallback_to_text_when_unsupported(registry):
    """When a text chunker is registered, unknown types fall back to it."""
    text_chunker = TextChunker()
    registry.register("text", text_chunker)

    # Getting "pdf" when only "text" is registered → returns text chunker
    chunker = registry.get("pdf")
    assert chunker is text_chunker


async def test_get_raises_when_no_text_fallback(registry):
    """Without a text chunker, unknown types raise."""
    with pytest.raises(UnsupportedContentType):
        registry.get("unknown")


async def test_chunk_delegates(registry):
    """chunk() calls the registered chunker."""
    registry.register("text", TextChunker())
    chunks = await registry.chunk("hello world", "text")
    assert len(chunks) == 1
    assert chunks[0].text == "hello world"


async def test_run_is_alias_for_chunk(registry):
    """run() is an alias for chunk()."""
    registry.register("text", TextChunker())
    chunks = await registry.run("hello", "text")
    assert len(chunks) == 1


async def test_error_message_lists_available(registry):
    """Error message lists registered chunkers when no fallback."""
    # Register only non-text chunker to avoid fallback
    registry.register("code", TextChunker())  # Use as placeholder
    with pytest.raises(UnsupportedContentType) as exc:
        registry.get("video")
    assert "code" in str(exc.value)
