"""Create source_bindings table (ADR-0004 connection hub).

Source Bindings replace the self-built connector accounts: the binding
stores only the authorization relationship + source identity; credentials
and sync mechanics live on the connection hub.

Revision ID: 008_add_source_bindings
Revises: 007_add_pipeline_fact_extraction_status
Create Date: 2026-08-09 20:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "008_add_source_bindings"
down_revision = "007_add_pipeline_fact_extraction_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_bindings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "entity_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("hub_account_id", sa.String(255), nullable=False),
        sa.Column(
            "sync_status",
            sa.String(20),
            server_default="active",
            nullable=False,
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "sync_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity_id",
            "hub_account_id",
            name="uq_source_bindings_entity_account",
        ),
    )


def downgrade() -> None:
    op.drop_table("source_bindings")
