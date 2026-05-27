"""Add sync_metadata to connectors

Revision ID: 004_add_sync_metadata
Revises: 003_add_pipeline_jobs_content_type
Create Date: 2026-05-27 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "004_add_sync_metadata"
down_revision = "003_add_pipeline_jobs_content_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "connectors",
        sa.Column(
            "sync_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("connectors", "sync_metadata")
