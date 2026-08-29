"""Integration tests for default extractor/chunker registries.

Verifies that get_default_registry() returns fully populated registries
and that PipelineOrchestrator works out of the box without manual registration.
"""

import pytest

from emerald.pipeline.extraction import get_default_registry as get_default_extractors
from emerald.pipeline.chunking import get_default_registry as get_default_chunkers
from emerald.pipeline.orchestrator import PipelineOrchestrator


# ---- Default registry population ----

async def test_default_extractor_registry_has_all_types():
    registry = get_default_extractors()
    expected = {
        "text", "code", "markdown", "pdf", "url", "image",
        "audio", "video", "json", "csv",
    }
    assert set(registry._extractors.keys()) == expected


async def test_default_chunker_registry_has_all_types():
    registry = get_default_chunkers()
    expected = {"text", "code", "markdown", "pdf", "conversation", "json", "csv"}
    assert set(registry._chunkers.keys()) == expected


# ---- text/markdown MIME parity (issue #4) ----

async def test_markdown_mime_extracts_and_chunks_by_structure():
    """text/markdown must not throw at extraction and must chunk by
    markdown structure (parity with the chunker side)."""
    extractors = get_default_extractors()
    chunkers = get_default_chunkers()

    md = "# Title\n\nSome prose.\n\n## Section\n\n- item one\n- item two\n"
    result = await extractors.extract(md, "text/markdown")
    assert result.text == md.rstrip()

    chunks = await chunkers.chunk(md, "text/markdown")
    assert chunks
    # MarkdownChunker splits on heading levels: the H1 and the H2 section
    # land in separate chunks rather than one flat text block
    assert any("Title" in c.text for c in chunks)
    assert any("Section" in c.text for c in chunks)
    assert not any(("Title" in c.text and "Section" in c.text) for c in chunks)


async def test_markdown_mime_family_aliases_extract():
    """The markdown MIME family (text/markdown, application/markdown)
    resolves to the registered markdown extractor."""
    extractors = get_default_extractors()
    for mime in ("text/markdown", "application/markdown"):
        result = await extractors.extract("**bold**", mime)
        assert result.text == "**bold**"


# ---- PipelineOrchestrator out-of-the-box ----

@pytest.mark.asyncio
async def test_orchestrator_default_registries_work():
    """PipelineOrchestrator() without args uses default registries."""
    orch = PipelineOrchestrator(use_db=False)
    # Should be able to look up text extractor/chunker
    ext = orch.extractors.get("text")
    chk = orch.chunkers.get("text")
    assert ext.supports("text")
    assert await chk.chunk("") == []
