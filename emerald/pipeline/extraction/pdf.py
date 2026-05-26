"""PDF extractor — text extraction with OCR fallback for image-only pages."""

from __future__ import annotations

import io

from emerald.core.exceptions import ExtractionError
from emerald.pipeline.extraction.base import BaseExtractor, ExtractedContent


class PDFExtractor(BaseExtractor):
    """Extracts text from PDFs using PyMuPDF.

    Falls back to Tesseract OCR for image-only pages without a text layer.
    """

    async def extract(self, content: bytes, **kwargs) -> ExtractedContent:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ExtractionError(
                content_type="pdf",
                reason="PyMuPDF not installed",
                retryable=False,
            )

        try:
            doc = fitz.open(stream=content, filetype="pdf")
        except Exception as e:
            raise ExtractionError(
                content_type="pdf",
                reason=f"Failed to open PDF: {e}",
                retryable=False,
            )

        text_parts = []
        for page_num in range(doc.page_count):
            page = doc[page_num]
            text = page.get_text()
            if text.strip():
                text_parts.append(f"[Page {page_num + 1}]\n{text}")
            else:
                # Image-only page: OCR fallback
                pix = page.get_pixmap(dpi=150)
                img_bytes = pix.tobytes("png")
                ocr_text = await self._ocr_fallback(img_bytes)
                text_parts.append(f"[Page {page_num + 1}]\n{ocr_text}")

        doc.close()
        full_text = "\n\n".join(text_parts)
        return ExtractedContent(
            text=full_text,
            content_type="pdf",
            metadata={"page_count": len(text_parts)},
        )

    async def _ocr_fallback(self, img_bytes: bytes) -> str:
        try:
            from PIL import Image
            import pytesseract

            img = Image.open(io.BytesIO(img_bytes))
            text = pytesseract.image_to_string(img, lang="chi_sim+eng")
            return text or "(OCR: no text detected)"
        except ImportError:
            return "(OCR unavailable)"
        except Exception as e:
            return f"(OCR error: {e})"

    def supports(self, content_type: str) -> bool:
        return content_type == "pdf"
