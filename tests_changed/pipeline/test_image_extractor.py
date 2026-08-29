"""Tests for ImageExtractor.

Pillow and Tesseract are mocked so tests run without heavy deps.
"""

from unittest.mock import MagicMock, patch

import pytest

from emerald.core.exceptions import ExtractionError
from emerald.pipeline.extraction.image import ImageExtractor


@pytest.fixture
def extractor():
    return ImageExtractor()


# ---- Supports ----

@pytest.mark.asyncio
async def test_supports_image(extractor):
    assert extractor.supports("image") is True
    assert extractor.supports("text") is False


# ---- Missing deps ----

@pytest.mark.asyncio
async def test_extract_missing_deps(extractor):
    with patch.dict("sys.modules", {"PIL": None, "pytesseract": None}):
        with pytest.raises(ExtractionError, match="Pillow / Tesseract not installed"):
            await extractor.extract(b"fake_image")


# ---- Normal extraction ----

@pytest.mark.asyncio
async def test_extract_ocr_success(extractor):
    """Successful OCR returns extracted text and metadata."""
    mock_img = MagicMock()
    mock_img.size = (800, 600)
    mock_img.convert.return_value = mock_img
    mock_img.filter.return_value = mock_img
    mock_img.point.return_value = mock_img

    with patch("PIL.Image.open", return_value=mock_img):
        with patch("pytesseract.image_to_string", return_value="Hello world"):
            result = await extractor.extract(b"fake_png")

    assert result.text == "Hello world"
    assert result.content_type == "image"
    assert result.metadata["image_size"] == (800, 600)


@pytest.mark.asyncio
async def test_extract_ocr_fallback_to_eng(extractor):
    """chi_sim+eng failure falls back to eng."""
    mock_img = MagicMock()
    mock_img.convert.return_value = mock_img
    mock_img.filter.return_value = mock_img
    mock_img.point.return_value = mock_img

    with patch("PIL.Image.open", return_value=mock_img):
        with patch(
            "pytesseract.image_to_string",
            side_effect=[RuntimeError("lang pack missing"), "fallback text"],
        ) as mock_ocr:
            result = await extractor.extract(b"fake_png")

    assert result.text == "fallback text"
    assert mock_ocr.call_count == 2
    # Second call should use lang="eng"
    assert mock_ocr.call_args_list[1][1].get("lang") == "eng"


# ---- Processing error ----

@pytest.mark.asyncio
async def test_extract_processing_error(extractor):
    """Image decode failure raises ExtractionError."""
    with patch("PIL.Image.open", side_effect=RuntimeError("corrupt")):
        with pytest.raises(ExtractionError, match="Image processing failed"):
            await extractor.extract(b"bad_data")


# ---- Preprocessing ----

@pytest.mark.asyncio
async def test_extract_applies_preprocessing(extractor):
    """Grayscale, denoise, and threshold are applied."""
    mock_img = MagicMock()
    mock_img.size = (100, 100)
    gray = MagicMock()
    denoised = MagicMock()
    thresholded = MagicMock()

    mock_img.convert.return_value = gray
    gray.filter.return_value = denoised
    denoised.point.return_value = thresholded

    with patch("PIL.Image.open", return_value=mock_img):
        with patch("pytesseract.image_to_string", return_value="ok"):
            await extractor.extract(b"img")

    mock_img.convert.assert_called_once_with("L")
    gray.filter.assert_called_once()
    denoised.point.assert_called_once()
