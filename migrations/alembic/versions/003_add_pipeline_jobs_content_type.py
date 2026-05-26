"""Add content_type to pipeline_jobs

Revision ID: 003_add_pipeline_jobs_content_type
Revises: 002_add_pgvector_embedding
Create Date: 2026-05-26 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "003_add_pipeline_jobs_content_type"
down_revision = "002_add_pgvector_embedding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipeline_jobs",
        sa.Column("content_type", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pipeline_jobs", "content_type")
