"""Add pgvector embedding column

Revision ID: 002_add_pgvector_embedding
Revises: 35500f582718
Create Date: 2026-05-25 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "002_add_pgvector_embedding"
down_revision = "35500f582718"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE embeddings DROP COLUMN embedding")
    op.execute("ALTER TABLE embeddings ADD COLUMN embedding vector(1536) NOT NULL")
    op.execute(
        "CREATE INDEX idx_embeddings_hnsw ON embeddings "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_embeddings_hnsw")
    op.execute("ALTER TABLE embeddings DROP COLUMN embedding")
    op.execute("ALTER TABLE embeddings ADD COLUMN embedding JSONB NOT NULL DEFAULT '{}'")
