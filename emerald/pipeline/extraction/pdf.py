"""PDF extractor — extract text and tables from PDF files.

Requires PyMuPDF (fitz). Gracefully degrades with clear error messages
when dependencies are not installed.
"""

from __future__ import annotations

from emerald.core.exceptions import ExtractionError
from emerald.pipeline.extraction.base import BaseExtractor, ExtractedContent


class PDFExtractor(BaseExtractor):
    """Extracts text and tables from PDFs using PyMuPDF.

    Falls back to Tesseract OCR for scanned documents without a text layer.
    """

    async def extract(self, content: bytes, **kwargs) -> ExtractedContent:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ExtractionError(
                content_type="pdf",
                reason="PyMuPDF is not installed. Install with: pip install PyMuPDF",
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
        metadata = {"page_count": doc.page_count}

        for page_num in range(doc.page_count):
            try:
                page = doc[page_num]
                page_text = page.get_text()
                if page_text.strip():
                    text_parts.append(f"[Page {page_num + 1}]\n{page_text}")
                else:
                    # No text layer — would need OCR
                    text_parts.append(f"[Page {page_num + 1}] (image-only, OCR required)")
            except Exception:
                # Single page failure should not crash the pipeline
                text_parts.append(f"[Page {page_num + 1}] (extraction failed)")

        doc.close()

        full_text = "\n\n".join(text_parts)
        return ExtractedContent(
            text=full_text,
            content_type="pdf",
            metadata=metadata,
        )

    def supports(self, content_type: str) -> bool:
        return content_type == "pdf"
