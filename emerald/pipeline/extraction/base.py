"""Base extractor interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ExtractedContent:
    """Output from an extractor."""

    text: str
    metadata: dict = field(default_factory=dict)
    content_type: str = "text"


class BaseExtractor(ABC):
    """Abstract base for content extractors.

    Each extractor handles one content_type (text, url, pdf, image, audio, video, code).
    """

    @abstractmethod
    async def extract(self, content: str | bytes, **kwargs) -> ExtractedContent:
        """Extract structured text from raw content."""

    @abstractmethod
    def supports(self, content_type: str) -> bool:
        """Check if this extractor handles the given content type."""


class ExtractionError(Exception):
    """Raised when extraction fails."""

    def __init__(
        self, content_type: str, reason: str, retryable: bool = True
    ) -> None:
        self.content_type = content_type
        self.reason = reason
        self.retryable = retryable
        super().__init__(f"Extraction failed for {content_type}: {reason}")
