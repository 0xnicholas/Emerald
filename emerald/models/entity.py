"""Entity ORM model."""

from __future__ import annotations

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from emerald.models.base import Base, TimestampMixin, UUIDMixin


class Entity(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("external_id", "type", name="uq_entities_external_type"),
    )

    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # user | project | organization | custom
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}"
    )
