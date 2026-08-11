"""Drop connectors table (ADR-0004 T4b — self-built connector retirement).

The self-built connectors (OAuth credentials, webhook secrets, per-provider
sync state) were retired in issue #7: the connection hub (Totem) owns
credentials/sync mechanics, and `source_bindings` (008) carries the
authorization relationship + source identity.

Revision ID: 009_drop_connectors
Revises: 008_add_source_bindings
Create Date: 2026-08-11 21:00:00.000000
"""

from alembic import op

# revision identifiers
revision = "009_drop_connectors"
down_revision = "008_add_source_bindings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("idx_connectors_entity", table_name="connectors")
    op.drop_table("connectors")


def downgrade() -> None:
    # The table shape is documented in 35500f582718 (initial schema) plus
    # 004_add_sync_metadata; restoring is an explicit ops decision (data
    # loss is one-way in practice).
    raise NotImplementedError(
        "Connector table retirement is not reversible; re-create from "
        "migrations 35500f582718 + 004 if ever needed."
    )
