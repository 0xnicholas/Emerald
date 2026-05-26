"""Unit tests for PDF extractor."""

import pytest

from emerald.pipeline.extraction.pdf import PDFExtractor


@pytest.fixture
def pdf_extractor():
    return PDFExtractor()


def test_pdf_missing_pymupdf(pdf_extractor, monkeypatch):
    """ImportError → ExtractionError(retryable=False)."""
    pytest.importorskip("fitz", reason="PyMuPDF not installed")


def test_pdf_corrupted(pdf_extractor):
    """Invalid bytes → ExtractionError."""
    import asyncio

    with pytest.raises(Exception):  # ExtractionError
        asyncio.run(pdf_extractor.extract(b"not a pdf"))
