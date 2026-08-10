"""Source Binding ORM model (ADR-0004).

A Source Binding is an external account authorized through the
connection hub: the authorization relationship + source identity.
Credential storage, OAuth and sync mechanics live on the hub, not here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from emerald.models.base import Base, TimestampMixin, UUIDMixin


class SourceBinding(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "source_bindings"
    __table_args__ = (
        UniqueConstraint(
            "entity_id",
            "hub_account_id",
            name="uq_source_bindings_entity_account",
        ),
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    # The connection id on the hub (Totem connection; hub_account_id keeps
    # the historic column name).
    hub_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sync_status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active", nullable=False
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    sync_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
