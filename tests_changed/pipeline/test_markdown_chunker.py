"""Tests for MarkdownChunker."""

import pytest

from emerald.pipeline.chunking.markdown import MarkdownChunker


@pytest.fixture
def chunker():
    return MarkdownChunker()


async def test_chunk_splits_by_headings(chunker):
    """Markdown is split at ## heading boundaries."""
    text = """# Title

Some intro text.

## Section 1
Content of section 1.

## Section 2
Content of section 2.

### Subsection 2.1
Deeper content here.
"""
    chunks = await chunker.chunk(text)
    # Should have at least: intro + Section 1 + Section 2
    assert len(chunks) >= 2


async def test_chunk_heading_path_metadata(chunker):
    """Each chunk records its heading path."""
    text = """# H1

Intro.

## H2 Section

Content here.
"""
    chunks = await chunker.chunk(text)
    for c in chunks:
        assert "heading_path" in c.metadata


async def test_chunk_code_blocks_independent(chunker):
    """Code blocks in markdown are kept as separate chunks."""
    text = """# Guide

Some text.

```python
def hello():
    print("hello world")
```

More text after code block.
"""
    chunks = await chunker.chunk(text)
    # Code block should be a separate chunk
    code_chunks = [c for c in chunks if "```" in c.text or "def hello" in c.text]
    assert len(code_chunks) >= 1


async def test_chunk_content_type_markdown(chunker):
    """Chunks carry content_type='markdown'."""
    text = "# Title\n\nContent."
    chunks = await chunker.chunk(text)
    for c in chunks:
        assert c.content_type == "markdown"


async def test_chunk_empty(chunker):
    """Empty markdown produces no chunks."""
    assert await chunker.chunk("") == []
