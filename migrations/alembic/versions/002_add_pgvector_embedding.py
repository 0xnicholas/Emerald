"""Add pgvector embedding column and relax embeddings constraints

Revision ID: 002_add_pgvector_embedding
Revises: 35500f582718
Create Date: 2026-05-25 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "002_add_pgvector_embedding"
down_revision = "35500f582718"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure pgvector extension is available
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ------------------------------------------------------------------
    # Relax embeddings table constraints to match business-code usage
    # ------------------------------------------------------------------
    # 1. Drop FK constraints that tied embeddings to PG-internal UUIDs.
    #    Business code uses external string IDs (same as Neo4j Entity.id).
    op.execute(
        """
        ALTER TABLE embeddings
        DROP CONSTRAINT IF EXISTS embeddings_document_id_fkey,
        DROP CONSTRAINT IF EXISTS embeddings_entity_id_fkey
        """
    )

    # 2. Drop old indexes on columns we are about to alter
    op.execute("DROP INDEX IF EXISTS idx_embeddings_chunk")
    op.execute("DROP INDEX IF EXISTS idx_embeddings_entity")
    op.execute("DROP INDEX IF EXISTS idx_embeddings_document")

    # 3. Alter column types
    #    chunk_id  -> VARCHAR(64)  to hold uuid4().hex / memory_id
    #    entity_id -> VARCHAR(255) to hold external entity IDs (Neo4j-compatible)
    #    document_id -> nullable    because memory path does not supply one
    op.execute("ALTER TABLE embeddings ALTER COLUMN chunk_id TYPE VARCHAR(64)")
    op.execute("ALTER TABLE embeddings ALTER COLUMN entity_id TYPE VARCHAR(255)")
    op.execute("ALTER TABLE embeddings ALTER COLUMN document_id DROP NOT NULL")

    # 4. Convert embedding from JSONB -> vector(1536)
    #    Guard against the default '{}' by normalising to an empty JSON array first.
    op.execute(
        """
        UPDATE embeddings
        SET embedding = '[]'::jsonb
        WHERE embedding = '{}'::jsonb OR embedding IS NULL
        """
    )
    op.execute(
        """
        ALTER TABLE embeddings
        ALTER COLUMN embedding TYPE vector(1536)
        USING embedding::text::vector(1536)
        """
    )

    # 5. Create HNSW index for approximate nearest-neighbour search
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_embeddings_hnsw ON embeddings
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )

    # 6. Re-create functional indexes on the new-typed columns
    op.create_index("idx_embeddings_chunk", "embeddings", ["chunk_id"])
    op.create_index("idx_embeddings_entity", "embeddings", ["entity_id"])
    op.create_index("idx_embeddings_document", "embeddings", ["document_id"])


def downgrade() -> None:
    # Reverse order of creation
    op.execute("DROP INDEX IF EXISTS idx_embeddings_hnsw")
    op.execute("DROP INDEX IF EXISTS idx_embeddings_document")
    op.execute("DROP INDEX IF EXISTS idx_embeddings_entity")
    op.execute("DROP INDEX IF EXISTS idx_embeddings_chunk")

    # Revert embedding column to JSONB
    op.execute(
        """
        ALTER TABLE embeddings
        ALTER COLUMN embedding TYPE JSONB
        USING embedding::text::jsonb
        """
    )

    # Restore strict schema
    op.execute("ALTER TABLE embeddings ALTER COLUMN document_id SET NOT NULL")
    op.execute(
        "ALTER TABLE embeddings ALTER COLUMN entity_id TYPE UUID USING entity_id::uuid"
    )
    op.execute(
        "ALTER TABLE embeddings ALTER COLUMN chunk_id TYPE UUID USING chunk_id::uuid"
    )

    op.create_foreign_key(
        "embeddings_document_id_fkey",
        "embeddings",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "embeddings_entity_id_fkey",
        "embeddings",
        "entities",
        ["entity_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_index("idx_embeddings_chunk", "embeddings", ["chunk_id"])
    op.create_index("idx_embeddings_entity", "embeddings", ["entity_id"])
    op.create_index("idx_embeddings_document", "embeddings", ["document_id"])
