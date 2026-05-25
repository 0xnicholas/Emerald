"""Add pgvector embedding column

Revision ID: 002_add_pgvector_embedding
Revises: 35500f582718
Create Date: 2026-05-25 00:00:00.000000
"""

from alembic import op

# revision identifiers
revision = "002_add_pgvector_embedding"
down_revision = "35500f582718"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # Idempotent: only convert if embedding is not already a vector type.
    # In production, run a data-migration batch before applying this.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'embeddings'
                  AND column_name = 'embedding'
                  AND udt_name = 'vector'
            ) THEN
                ALTER TABLE embeddings
                    ALTER COLUMN embedding TYPE vector(1536)
                    USING embedding::text::vector(1536);
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_embeddings_hnsw ON embeddings "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_embeddings_hnsw")
    op.execute("ALTER TABLE embeddings DROP COLUMN embedding")
    op.execute("ALTER TABLE embeddings ADD COLUMN embedding JSONB NOT NULL DEFAULT '{}'")
