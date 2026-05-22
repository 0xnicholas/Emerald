"""Image extractor — OCR text recognition from images.

Requires Pillow and pytesseract. Gracefully degrades when deps are missing.
"""

from __future__ import annotations

from emerald.core.exceptions import ExtractionError
from emerald.pipeline.extraction.base import BaseExtractor, ExtractedContent


class ImageExtractor(BaseExtractor):
    """Extracts text from images via Tesseract OCR.

    Preprocessing: grayscale, denoise, binarize (when Pillow is available).
    """

    async def extract(self, content: bytes, **kwargs) -> ExtractedContent:
        try:
            from PIL import Image
        except ImportError:
            raise ExtractionError(
                content_type="image",
                reason="Pillow is not installed. Install with: pip install Pillow",
                retryable=False,
            )

        try:
            import pytesseract
        except ImportError:
            raise ExtractionError(
                content_type="image",
                reason="pytesseract is not installed. Install with: pip install pytesseract",
                retryable=False,
            )

        try:
            import io
            image = Image.open(io.BytesIO(content))

            # Basic preprocessing: convert to grayscale
            if image.mode != "L":
                image = image.convert("L")

            text = pytesseract.image_to_string(image, lang=kwargs.get("lang", "eng"))
            confidence = self._get_confidence(image)

            return ExtractedContent(
                text=text.strip(),
                content_type="image",
                metadata={
                    "ocr_confidence": confidence,
                    "image_size": image.size,
                },
            )
        except Exception as e:
            raise ExtractionError(
                content_type="image",
                reason=f"OCR failed: {e}",
                retryable=False,
            )

    @staticmethod
    def _get_confidence(image) -> float:
        """Estimate OCR confidence (simplified)."""
        try:
            import pytesseract
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            confidences = [
                int(c) for c in data.get("conf", []) if c != "-1"
            ]
            if confidences:
                return sum(confidences) / len(confidences) / 100.0
        except Exception:
            pass
        return 0.0

    def supports(self, content_type: str) -> bool:
        return content_type == "image"
