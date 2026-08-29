"""Unit tests for Image extractor."""

import pytest

from emerald.pipeline.extraction.image import ImageExtractor


@pytest.fixture
def image_extractor():
    return ImageExtractor()


def test_image_missing_tesseract(image_extractor, monkeypatch):
    pytest.importorskip("pytesseract", reason="Tesseract not installed")
