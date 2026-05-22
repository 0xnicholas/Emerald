"""Code extractor — preserves code structure for chunking.

The extractor largely passes code through but strips irrelevant artifacts
and normalizes whitespace. The heavy structural analysis happens in CodeChunker.
"""

from __future__ import annotations

from emerald.pipeline.extraction.base import BaseExtractor, ExtractedContent


class CodeExtractor(BaseExtractor):
    """Extracts code content, preserving structure and comments.

    Auto-detects language via pygments when language="auto".
    """

    async def extract(self, content: str, **kwargs) -> ExtractedContent:
        language = kwargs.get("language", "auto")

        # Auto-detect language
        if language == "auto":
            language = self._detect_language(content)

        # Basic cleaning: normalize line endings, strip trailing whitespace
        cleaned = content.replace("\r\n", "\n").strip()
        # Remove excessive blank lines (> 2 consecutive)
        import re

        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

        return ExtractedContent(
            text=cleaned,
            content_type="code",
            metadata={"language": language},
        )

    def supports(self, content_type: str) -> bool:
        return content_type == "code"

    @staticmethod
    def _detect_language(code: str) -> str:
        """Simple heuristic language detection."""
        first_line = code.strip().split("\n")[0] if code.strip() else ""

        if first_line.startswith("def ") or first_line.startswith("class "):
            return "python"
        if first_line.startswith("function ") or first_line.startswith("const "):
            return "javascript"
        if first_line.startswith("package ") or first_line.startswith("import ("):
            return "go"
        if first_line.startswith("fn ") or first_line.startswith("use "):
            return "rust"
        if first_line.startswith("import ") and "from " in first_line:
            return "python"

        return "unknown"
