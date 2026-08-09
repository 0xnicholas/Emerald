"""CSV chunker — row-preserving splitting with header context.

Strategy (spec issue #1):
- The first line is treated as the header and is repeated as the prefix of
  every chunk, so a bare row never loses its column context.
- Rows are grouped into bounded batches (header + rows per chunk).
- Headerless files are handled by the same path: the first data line simply
  becomes the repeated prefix — no data is lost (a headerless file is
  indistinguishable from a header+rows file by inspection).
- Malformed CSV (inconsistent field counts, unparseable rows) logs a warning
  and falls back to the text chunker; the pipeline never breaks.
"""

from __future__ import annotations

import csv as csv_module
import io
from typing import Any

import structlog

from emerald.pipeline.chunking.base import BaseChunker, Chunk
from emerald.pipeline.chunking.text import TextChunker

logger = structlog.get_logger(__name__)


class CsvChunker(BaseChunker):
    """Chunks CSV by rows, keeping the header line with every chunk."""

    target_size = 512
    overlap_size = 0
    _chars_per_token = 4

    def __init__(self) -> None:
        self._fallback = TextChunker()

    async def chunk(self, text: str, **kwargs: Any) -> list[Chunk]:
        """Split CSV text into header-prefixed row batches."""
        if not text.strip():
            return []

        # Validate with the csv module (handles quoted fields correctly):
        # every row must have the same field count as the first line.
        try:
            parsed = list(csv_module.reader(io.StringIO(text)))
        except Exception as exc:
            logger.warning("chunking.csv_parse_failed", error=str(exc))
            return await self._fallback.chunk(text, **kwargs)
        if len(parsed) > 1 and any(
            len(row) != len(parsed[0]) for row in parsed[1:]
        ):
            logger.warning(
                "chunking.csv_field_mismatch",
                header_fields=len(parsed[0]),
                rows=len(parsed),
            )
            return await self._fallback.chunk(text, **kwargs)

        lines = [ln.rstrip("\r") for ln in text.splitlines() if ln.strip()]
        if not lines:
            return []

        budget = self.target_size * self._chars_per_token
        header = lines[0]
        rows = lines[1:]

        if not rows:
            # Header-only CSV: keep the single line as one chunk.
            return [self._make_chunk([header], 1, 1, 0)]

        chunks: list[Chunk] = []
        batch: list[str] = [header]
        batch_chars = len(header)
        batch_first_row = 2  # 1-based line number of the first data row
        index = 0  # ordinal chunk counter

        for i, row in enumerate(rows, start=2):
            row_chars = len(row) + 1  # +1 for the newline separator
            if len(batch) > 1 and batch_chars + row_chars > budget:
                chunks.append(
                    self._make_chunk(batch, batch_first_row, i - 1, index)
                )
                batch = [header]
                batch_chars = len(header)
                batch_first_row = i
                index += 1
            batch.append(row)
            batch_chars += row_chars

        if len(batch) > 1:
            chunks.append(
                self._make_chunk(batch, batch_first_row, len(lines), index)
            )
        return chunks

    def _make_chunk(
        self, batch: list[str], start: int, end: int, index: int
    ) -> Chunk:
        text = "\n".join(batch)
        return Chunk(
            text=text,
            index=index,
            token_count=max(1, len(text) // self._chars_per_token),
            content_type="csv",
            metadata={
                "kind": "csv_rows",
                "start_row": start,
                "end_row": end,
                "row_count": len(batch) - 1,  # header excluded
            },
        )
