from __future__ import annotations

"""Structured summary fields
Adds typed summary output columns"""

from alembic import op
import sqlalchemy as sa


revision = "20250323_000003"
down_revision = "20250320_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add structured summary columns"""
    op.add_column("memory_nodes", sa.Column("commitments", sa.Text(), nullable=False, server_default="[]"))
    op.add_column("memory_nodes", sa.Column("revisions", sa.Text(), nullable=False, server_default="[]"))
    op.add_column("memory_nodes", sa.Column("preferences", sa.Text(), nullable=False, server_default="[]"))
    op.add_column("memory_nodes", sa.Column("relationship_guidance", sa.Text(), nullable=False, server_default="[]"))
    op.add_column("memory_nodes", sa.Column("self_model_updates", sa.Text(), nullable=False, server_default="[]"))


def downgrade() -> None:
    """Drop structured summary columns"""
    op.drop_column("memory_nodes", "self_model_updates")
    op.drop_column("memory_nodes", "relationship_guidance")
    op.drop_column("memory_nodes", "preferences")
    op.drop_column("memory_nodes", "revisions")
    op.drop_column("memory_nodes", "commitments")
