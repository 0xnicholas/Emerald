"""Fast lane chunk ORM model — stores coarse, immediately-searchable chunks.

These chunks exist only while the full pipeline is running (or as a temporary
searchable copy for small writes).  They are removed/archived once the
corresponding indexed memories are ready.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from emerald.models.base import Base


class FastLaneChunk(Base):
    __tablename__ = "fast_lane_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    # entity_id matches Neo4j Entity node id (external string), not entities.id UUID.
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Stored as JSONB for portability; production can switch to pgvector VECTOR.
    embedding: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    stage: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="fast_lane"
    )
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
