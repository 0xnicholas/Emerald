"""Base chunker interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class Chunk:
    """A single semantic chunk ready for embedding."""

    text: str
    index: int
    token_count: int = 0
    content_type: str = "text"
    metadata: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        return uuid4().hex


class BaseChunker(ABC):
    """Abstract base for content-type-aware chunking strategies."""

    @abstractmethod
    def chunk(self, text: str, **kwargs) -> list[Chunk]:
        """Split text into semantic chunks."""

    @property
    @abstractmethod
    def target_size(self) -> int:
        """Target chunk size in tokens."""

    @property
    @abstractmethod
    def overlap_size(self) -> int:
        """Overlap between adjacent chunks in tokens."""
