"""Add fast_lane_chunks table for immediate-retrieval raw segments.

Revision ID: 006_add_fast_lane_chunks
Revises: 005_add_fulltext_indexes
Create Date: 2026-06-28 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "006_add_fast_lane_chunks"
down_revision = "005_add_fulltext_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fast_lane_chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("entity_id", sa.String(255), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("embedding", postgresql.JSONB, nullable=False),
        sa.Column("stage", sa.String(20), nullable=False, server_default="fast_lane"),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("dimensions", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_fast_lane_entity", "fast_lane_chunks", ["entity_id"])
    op.create_index("idx_fast_lane_stage", "fast_lane_chunks", ["stage"])


def downgrade() -> None:
    op.drop_index("idx_fast_lane_stage", table_name="fast_lane_chunks")
    op.drop_index("idx_fast_lane_entity", table_name="fast_lane_chunks")
    op.drop_table("fast_lane_chunks")
