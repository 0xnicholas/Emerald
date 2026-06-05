"""Add PostgreSQL full-text indexes for keyword search

Revision ID: 005_add_fulltext_indexes
Revises: 004_add_sync_metadata
Create Date: 2026-06-01 00:00:00.000000
"""

from alembic import op

# revision identifiers
revision = "005_add_fulltext_indexes"
down_revision = "004_add_sync_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pg_trgm for fuzzy similarity (works across languages)
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Add text column if not present (needed for keyword search)
    op.execute(
        """
        ALTER TABLE embeddings
        ADD COLUMN IF NOT EXISTS text TEXT
        """
    )

    # tsvector column for full-text search (generated from text)
    op.execute(
        """
        ALTER TABLE embeddings
        ADD COLUMN IF NOT EXISTS text_tsv tsvector
        GENERATED ALWAYS AS (to_tsvector('simple', COALESCE(text, ''))) STORED
        """
    )

    # GIN index on tsvector
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_embeddings_tsv
        ON embeddings USING gin (text_tsv)
        """
    )

    # GIN index on text using trigram ops
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_embeddings_trgm
        ON embeddings USING gin (text gin_trgm_ops)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_embeddings_trgm")
    op.execute("DROP INDEX IF EXISTS idx_embeddings_tsv")
    op.execute("ALTER TABLE embeddings DROP COLUMN IF EXISTS text_tsv")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
