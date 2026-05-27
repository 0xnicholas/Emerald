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
    # Alembic's default alembic_version.version_num is VARCHAR(32);
    # our revision ID is 33 chars. Widen it first.
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)")

    op.add_column(
        "pipeline_jobs",
        sa.Column("content_type", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pipeline_jobs", "content_type")
