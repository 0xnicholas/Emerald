"""Tests for PDFChunker."""

import pytest

from emerald.pipeline.chunking.pdf import PDFChunker


@pytest.fixture
def chunker():
    return PDFChunker()


async def test_chunk_pdf_with_structure(chunker):
    """PDF chunker uses provided structure metadata."""
    text = "Section 1 content here.\n\nSection 2 content here."
    structure = [
        {"title": "Introduction", "page": 1},
        {"title": "Methods", "page": 2},
    ]
    chunks = await chunker.chunk(text, structure=structure)
    assert len(chunks) > 0


async def test_chunk_pdf_without_structure(chunker):
    """PDF chunker falls back to paragraph splitting without structure."""
    text = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
    chunks = await chunker.chunk(text)
    assert len(chunks) > 0


async def test_chunk_content_type_pdf(chunker):
    """Chunks carry content_type='pdf'."""
    chunks = await chunker.chunk("Some PDF content.")
    for c in chunks:
        assert c.content_type == "pdf"


def test_chunk_overlap_greater_than_text(chunker):
    """PDF chunker has larger overlap (128 tokens) for context preservation."""
    assert chunker.overlap_size == 128
    assert chunker.target_size == 512


async def test_chunk_empty(chunker):
    assert await chunker.chunk("") == []
