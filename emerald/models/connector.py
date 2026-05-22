"""Connector ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import BYTEA, UUID
from sqlalchemy.orm import Mapped, mapped_column

from emerald.models.base import Base, TimestampMixin, UUIDMixin


class Connector(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "connectors"
    __table_args__ = (
        UniqueConstraint("entity_id", "provider", name="uq_connectors_entity_provider"),
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    credentials: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    webhook_secret: Mapped[str | None] = mapped_column(String(255))
    sync_status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active", nullable=False
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
