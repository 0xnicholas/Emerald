"""Add fact_extraction_status + memory_count to pipeline_jobs (P1.2b).

These fields are surfaced by ``GET /v1/pipelines/{id}`` so SDK/MCP clients
can distinguish "pipeline done but extracted zero memories" from "pipeline
still running".  The Pydantic SDK already documents
``fact_extraction_status`` and ``memory_count`` on ``PipelineStatus``; the
DB and route were the missing pieces.

Revision ID: 007_add_pipeline_fact_extraction_status
Revises: 006_add_fast_lane_chunks
Create Date: 2026-06-30 18:55:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "007_add_pipeline_fact_extraction_status"
down_revision = "006_add_fast_lane_chunks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipeline_jobs",
        sa.Column("fact_extraction_status", sa.String(20), nullable=True),
    )
    op.add_column(
        "pipeline_jobs",
        sa.Column(
            "memory_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("pipeline_jobs", "memory_count")
    op.drop_column("pipeline_jobs", "fact_extraction_status")
