"""Base chunker interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from emerald.core.mentions import Mention


@dataclass
class Chunk:
    """A single semantic chunk ready for embedding.

    The ``id`` field defaults to a random UUID but can be overwritten
    (e.g. with a ``memory_id``) so that the graph node and the vector-store
    row share the same canonical identifier.
    """

    text: str
    index: int
    token_count: int = 0
    content_type: str = "text"
    metadata: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid4().hex)
    # LLM fact extraction metadata
    memory_type: str = "fact"
    internal_type: str | None = None
    confidence: float = 0.8
    provenance: str = "explicit_statement"
    summary: str = ""
    valid_until: datetime | None = None
    # Named entities mentioned by this chunk (B3 NER) — populated by the
    # rule path (deterministic gazetteer) or the LLM fact-extraction path.
    mentions: list[Mention] = field(default_factory=list)


class BaseChunker(ABC):
    """Abstract base for content-type-aware chunking strategies."""

    @abstractmethod
    async def chunk(self, text: str, **kwargs) -> list[Chunk]:
        """Split text into semantic chunks."""

    @property
    @abstractmethod
    def target_size(self) -> int:
        """Target chunk size in tokens."""

    @property
    @abstractmethod
    def overlap_size(self) -> int:
        """Overlap between adjacent chunks in tokens."""
