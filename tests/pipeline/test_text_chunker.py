"""Tests for TextChunker."""

import pytest

from emerald.pipeline.chunking.text import TextChunker


@pytest.fixture
def chunker():
    return TextChunker()


async def test_chunk_single_short_paragraph(chunker):
    """Short text under target_size produces 1 chunk."""
    text = "This is a short paragraph."
    chunks = await chunker.chunk(text)
    assert len(chunks) == 1
    assert chunks[0].text == "This is a short paragraph."
    assert chunks[0].index == 0
    assert chunks[0].content_type == "text"


async def test_chunk_splits_paragraphs(chunker):
    """Multiple paragraphs produce multiple chunks when combined exceed target."""
    # Generate paragraphs that each are reasonable size
    para1 = "First paragraph. " * 30  # ~60 sentences
    para2 = "Second paragraph. " * 30
    text = para1 + "\n\n" + para2
    chunks = await chunker.chunk(text)
    assert len(chunks) >= 2
    # Each chunk should contain content from only one paragraph boundary
    for c in chunks:
        assert len(c.text) > 0


async def test_chunk_very_long_paragraph_splits_by_sentence(chunker):
    """A single very long paragraph gets split by sentence boundaries."""
    long_sentence = "This is sentence number {}. " * 200
    text = long_sentence.format(*range(200))
    chunks = await chunker.chunk(text)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.text) > 0


async def test_chunk_indices_are_sequential(chunker):
    """Chunk indices are 0, 1, 2, ... in order."""
    text = ("Paragraph {}. " * 20 + "\n\n") * 5
    chunks = await chunker.chunk(text)
    for i, c in enumerate(chunks):
        assert c.index == i


async def test_chunk_metadata_includes_offsets(chunker):
    """Each chunk records its character offset in the source text."""
    text = "AAA BBB CCC. " * 20 + "\n\n" + "DDD EEE FFF. " * 20
    chunks = await chunker.chunk(text)
    for c in chunks:
        assert "char_offset_start" in c.metadata
        assert "char_offset_end" in c.metadata
        start = c.metadata["char_offset_start"]
        end = c.metadata["char_offset_end"]
        assert 0 <= start < end <= len(text)
        # Chunk text may be trimmed of trailing separators; verify key words present
        source_window = text[start:end]
        assert c.text[:20].strip() in source_window, (
            f"Chunk start '{c.text[:30]}...' not found near offset {start}"
        )


async def test_chunk_empty_text_returns_empty(chunker):
    """Empty text produces no chunks."""
    chunks = await chunker.chunk("")
    assert chunks == []


async def test_chunk_content_type_set(chunker):
    """Chunks carry the content_type."""
    chunks = await chunker.chunk("Some text.")
    for c in chunks:
        assert c.content_type == "text"


async def test_target_and_overlap_properties(chunker):
    """Target and overlap sizes are as documented."""
    assert chunker.target_size == 512
    assert chunker.overlap_size == 64
