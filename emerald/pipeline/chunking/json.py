"""JSON chunker — structural splitting for JSON payloads.

Strategy (spec issue #1):
- Top-level arrays are chunked per element; small elements are merged into
  bounded batches so large payloads do not explode into thousands of chunks.
- Top-level objects are chunked per key — each key becomes its own chunk.
- Nested structures are NOT recursed into: top-level granularity only.
- Malformed input falls back to the text chunker; the pipeline never breaks.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from emerald.pipeline.chunking.base import BaseChunker, Chunk
from emerald.pipeline.chunking.text import TextChunker

logger = structlog.get_logger(__name__)


class JsonChunker(BaseChunker):
    """Chunks JSON by top-level structure (array elements / object keys)."""

    target_size = 512
    overlap_size = 0
    _chars_per_token = 4

    def __init__(self) -> None:
        self._fallback = TextChunker()

    async def chunk(self, text: str, **kwargs: Any) -> list[Chunk]:
        """Split a JSON payload into structural chunks."""
        if not text.strip():
            return []

        try:
            data = json.loads(text)
        except Exception as exc:
            logger.warning("chunking.json_parse_failed", error=str(exc))
            return await self._fallback.chunk(text, **kwargs)

        if isinstance(data, list):
            return self._chunk_list(data)
        if isinstance(data, dict):
            return self._chunk_dict(data)
        # Scalar top-level JSON (string/number/bool) has no structure to keep.
        return await self._fallback.chunk(text, **kwargs)

    def _chunk_list(self, data: list[Any]) -> list[Chunk]:
        """Chunk array elements, merging small elements into bounded batches."""
        budget = self.target_size * self._chars_per_token
        chunks: list[Chunk] = []
        batch: list[Any] = []
        batch_chars = 0
        index = 0  # global record index across batches
        ordinal = 0  # ordinal chunk counter

        for item in data:
            # +2 accounts for the ", " separator between serialized elements.
            item_chars = len(json.dumps(item, ensure_ascii=False)) + 2
            if batch and batch_chars + item_chars > budget:
                start = index - len(batch)
                chunks.append(
                    self._make_array_chunk(batch, start, index - 1, ordinal)
                )
                batch = []
                batch_chars = 0
                ordinal += 1
            batch.append(item)
            batch_chars += item_chars
            index += 1

        if batch:
            start = index - len(batch)
            chunks.append(
                self._make_array_chunk(batch, start, index - 1, ordinal)
            )
        return chunks

    def _make_array_chunk(
        self, batch: list[Any], start: int, end: int, index: int
    ) -> Chunk:
        text = json.dumps(batch, ensure_ascii=False)
        return Chunk(
            text=text,
            index=index,
            token_count=max(1, len(text) // self._chars_per_token),
            content_type="json",
            metadata={
                "kind": "json_array",
                "start_index": start,
                "end_index": end,
                "record_count": len(batch),
            },
        )

    def _chunk_dict(self, data: dict[Any, Any]) -> list[Chunk]:
        """Chunk an object per top-level key — each key is a chunk."""
        chunks: list[Chunk] = []
        for i, (key, value) in enumerate(data.items()):
            text = json.dumps({key: value}, ensure_ascii=False)
            chunks.append(
                Chunk(
                    text=text,
                    index=i,
                    token_count=max(1, len(text) // self._chars_per_token),
                    content_type="json",
                    metadata={"kind": "json_object_key", "key": key},
                )
            )
        return chunks
