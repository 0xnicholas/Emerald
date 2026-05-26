"""Image extractor — OCR with preprocessing pipeline."""

from __future__ import annotations

import io

from PIL import ImageFilter

from emerald.core.exceptions import ExtractionError
from emerald.pipeline.extraction.base import BaseExtractor, ExtractedContent


class ImageExtractor(BaseExtractor):
    """Extracts text from images via Tesseract OCR.

    Preprocessing: grayscale → median denoise → threshold.
    """

    async def extract(self, content: bytes, **kwargs) -> ExtractedContent:
        try:
            from PIL import Image
            import pytesseract
        except ImportError:
            raise ExtractionError(
                content_type="image",
                reason="Pillow / Tesseract not installed",
                retryable=False,
            )

        try:
            img = Image.open(io.BytesIO(content))
            # Preprocess: grayscale → denoise → threshold
            gray = img.convert("L")
            denoised = gray.filter(ImageFilter.MedianFilter(size=3))
            thresh = denoised.point(lambda x: 0 if x < 128 else 255, "1")

            try:
                text = pytesseract.image_to_string(thresh, lang="chi_sim+eng")
            except Exception:
                text = pytesseract.image_to_string(thresh, lang="eng")

            return ExtractedContent(
                text=text,
                content_type="image",
                metadata={"image_size": img.size},
            )
        except Exception as e:
            raise ExtractionError(
                content_type="image",
                reason=f"Image processing failed: {e}",
                retryable=False,
            )

    def supports(self, content_type: str) -> bool:
        return content_type == "image"
