"""Error path tests — verify graceful degradation when deps are missing."""

import pytest

from emerald.core.exceptions import ExtractionError
from emerald.pipeline.extraction.pdf import PDFExtractor
from emerald.pipeline.extraction.image import ImageExtractor
from emerald.pipeline.extraction.audio import AudioExtractor
from emerald.pipeline.extraction.video import VideoExtractor


# ---- PDF extractor error paths ----

@pytest.mark.asyncio
async def test_pdf_extractor_missing_pymupdf():
    """When PyMuPDF is not installed, raises ExtractionError(not retryable)."""
    import sys
    sys.modules.pop("fitz", None)

    extractor = PDFExtractor()
    with pytest.raises(ExtractionError) as exc:
        await extractor.extract(b"%PDF-1.4 fake pdf content")
    assert exc.value.retryable is False
    assert "PyMuPDF" in str(exc.value)


@pytest.mark.asyncio
async def test_pdf_extractor_corrupted_file():
    """Corrupted PDF raises ExtractionError(not retryable)."""
    pytest.importorskip("fitz", reason="PyMuPDF not installed")

    import fitz

    extractor = PDFExtractor()
    with pytest.raises(ExtractionError) as exc:
        await extractor.extract(b"not a real pdf")
    assert exc.value.retryable is False


# ---- Image extractor error paths ----

@pytest.mark.asyncio
async def test_image_extractor_handles_missing_dependency():
    """ImageExtractor raises ExtractionError when deps are unavailable."""
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        # pytesseract not installed — extraction should fail with clear message
        extractor = ImageExtractor()
        with pytest.raises(ExtractionError) as exc:
            await extractor.extract(b"fake image bytes")
        assert exc.value.retryable is False
        assert "pytesseract" in str(exc.value).lower()
    else:
        # pytesseract IS installed — skip this test (can't simulate missing dep cleanly)
        pytest.skip("pytesseract is installed, cannot simulate missing dependency")


# ---- Audio extractor error paths ----

@pytest.mark.asyncio
async def test_audio_extractor_missing_whisper(monkeypatch):
    """When faster-whisper is not installed, raises ExtractionError(not retryable)."""
    import sys
    sys.modules.pop("faster_whisper", None)

    extractor = AudioExtractor()
    with pytest.raises(ExtractionError) as exc:
        await extractor.extract(b"fake audio bytes")
    assert exc.value.retryable is False
    assert "faster-whisper" in str(exc.value)


# ---- Video extractor error paths ----

@pytest.mark.asyncio
async def test_video_extractor_missing_ffmpeg(monkeypatch):
    """When ffmpeg is not on PATH, raises ExtractionError(not retryable)."""
    import shutil
    original_which = shutil.which

    def mock_which(cmd):
        if cmd == "ffmpeg":
            return None
        return original_which(cmd)

    monkeypatch.setattr(shutil, "which", mock_which)

    extractor = VideoExtractor()
    with pytest.raises(ExtractionError) as exc:
        await extractor.extract(b"fake video bytes")
    assert exc.value.retryable is False
    assert "ffmpeg" in str(exc.value)


# ---- Pipeline error paths ----

@pytest.mark.asyncio
async def test_engine_handles_unsupported_content_type():
    """Engine gracefully handles unsupported content types."""
    from emerald.core.engine import MemoryEngine
    from emerald.core.extractor import ExtractorRegistry
    from emerald.pipeline.extraction.registry import UnsupportedContentType

    # Engine with NO extractors registered
    engine = MemoryEngine(extractor_registry=ExtractorRegistry())

    with pytest.raises(UnsupportedContentType):
        await engine.add("test", entity_id="user_1", content_type="unknown_type")


@pytest.mark.asyncio
async def test_engine_handles_empty_content():
    """Engine correctly propagates EmptyContentError from extractor."""
    from emerald.core.engine import MemoryEngine
    from emerald.core.extractor import ExtractorRegistry
    from emerald.pipeline.extraction.text import TextExtractor
    from emerald.core.exceptions import EmptyContentError

    extractors = ExtractorRegistry()
    extractors.register("text", TextExtractor())
    engine = MemoryEngine(extractor_registry=extractors)

    with pytest.raises(EmptyContentError):
        await engine.add("   ", entity_id="user_1")


# ---- Search with embedding failure ----


@pytest.mark.asyncio
async def test_search_handles_embedding_failure():
    """Search gracefully handles embedding generation failure."""
    from emerald.core.search import SearchOrchestrator, SearchMode
    from emerald.core.graph import GraphStore

    # Use graph store for memory search fallback, no embedder
    graph = GraphStore(use_db=False)
    await graph.create_memory("test content", entity_id="user_1")

    orchestrator = SearchOrchestrator(graph=graph, embedder=None)

    # RAG search without embedder should return empty (not crash)
    results = await orchestrator.search(
        "test", entity_id="user_1", search_mode=SearchMode.RAG,
    )
    assert results.results == []

    # Hybrid search should still get memory results
    results = await orchestrator.search(
        "test", entity_id="user_1", search_mode=SearchMode.HYBRID,
    )
    assert len(results.results) > 0  # From memory path
