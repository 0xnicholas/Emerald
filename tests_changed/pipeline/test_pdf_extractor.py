"""Tests for PDFExtractor.

PyMuPDF and Tesseract are mocked so tests run without heavy deps.
"""

import io
from unittest.mock import MagicMock, patch

import pytest

from emerald.core.exceptions import ExtractionError
from emerald.pipeline.extraction.pdf import PDFExtractor


@pytest.fixture
def extractor():
    return PDFExtractor()


@pytest.fixture
def fake_pdf_bytes():
    """Return minimal valid-looking PDF bytes."""
    return b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n>>\nendobj\nxref\ntrailer\n<<\n/Size 1\n>>\nstartxref\n9\n%%EOF"


# ---- Supports ----

@pytest.mark.asyncio
async def test_supports_pdf(extractor):
    assert extractor.supports("pdf") is True
    assert extractor.supports("text") is False


# ---- PyMuPDF missing ----

@pytest.mark.asyncio
async def test_extract_pymupdf_not_installed(extractor):
    with patch.dict("sys.modules", {"fitz": None}):
        with pytest.raises(ExtractionError, match="PyMuPDF not installed"):
            await extractor.extract(b"anything")


# ---- Normal extraction ----

@pytest.mark.asyncio
async def test_extract_single_page(extractor, fake_pdf_bytes):
    """Text extraction returns page content."""
    mock_page = MagicMock()
    mock_page.get_text.return_value = "Hello world"

    mock_doc = MagicMock()
    mock_doc.page_count = 1
    mock_doc.__getitem__ = lambda self, i: mock_page
    mock_doc.close = MagicMock()

    with patch("fitz.open", return_value=mock_doc):
        result = await extractor.extract(fake_pdf_bytes)

    assert "Hello world" in result.text
    assert result.content_type == "pdf"
    assert result.metadata.get("page_count") == 1


@pytest.mark.asyncio
async def test_extract_multiple_pages(extractor, fake_pdf_bytes):
    """Multi-page PDF concatenates pages with markers."""
    pages = [
        MagicMock(get_text=lambda: "Page one"),
        MagicMock(get_text=lambda: "Page two"),
    ]

    mock_doc = MagicMock()
    mock_doc.page_count = 2
    mock_doc.__getitem__ = lambda self, i: pages[i]
    mock_doc.close = MagicMock()

    with patch("fitz.open", return_value=mock_doc):
        result = await extractor.extract(fake_pdf_bytes)

    assert "[Page 1]" in result.text
    assert "[Page 2]" in result.text
    assert "Page one" in result.text
    assert "Page two" in result.text


# ---- Corrupted PDF ----

@pytest.mark.asyncio
async def test_extract_corrupted_pdf(extractor):
    """Corrupted PDF raises ExtractionError and does not crash."""
    with patch("fitz.open", side_effect=RuntimeError("damaged")):
        with pytest.raises(ExtractionError, match="Failed to open PDF"):
            await extractor.extract(b"not a pdf")


# ---- OCR fallback ----

@pytest.mark.asyncio
async def test_extract_image_only_page_ocr_fallback(extractor, fake_pdf_bytes):
    """Page with no text triggers OCR fallback."""
    mock_page = MagicMock()
    mock_page.get_text.return_value = "   "  # whitespace only

    mock_pix = MagicMock()
    mock_pix.tobytes.return_value = b"pngdata"
    mock_page.get_pixmap.return_value = mock_pix

    mock_doc = MagicMock()
    mock_doc.page_count = 1
    mock_doc.__getitem__ = lambda self, i: mock_page
    mock_doc.close = MagicMock()

    with patch("fitz.open", return_value=mock_doc):
        with patch.object(
            extractor, "_ocr_fallback", return_value="OCR text"
        ) as mock_ocr:
            result = await extractor.extract(fake_pdf_bytes)

    assert "OCR text" in result.text
    mock_ocr.assert_called_once_with(b"pngdata")


@pytest.mark.asyncio
async def test_ocr_fallback_missing_deps(extractor):
    """OCR without Pillow/Tesseract returns graceful message."""
    with patch.dict("sys.modules", {"PIL": None, "pytesseract": None}):
        result = await extractor._ocr_fallback(b"img")
    assert result == "(OCR unavailable)"


@pytest.mark.asyncio
async def test_ocr_fallback_error(extractor):
    """OCR runtime error is swallowed gracefully."""
    with patch("PIL.Image.open", side_effect=RuntimeError("bad image")):
        result = await extractor._ocr_fallback(b"img")
    assert "OCR error" in result
