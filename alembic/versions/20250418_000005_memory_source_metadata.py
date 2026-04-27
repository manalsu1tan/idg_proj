from __future__ import annotations

"""Memory source metadata
Tracks ingest provenance fields on nodes"""

from alembic import op
import sqlalchemy as sa


revision = "20250418_000005"
down_revision = "20250329_000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add source metadata columns and indexes"""
    op.add_column("memory_nodes", sa.Column("source_type", sa.String(length=64), nullable=True))
    op.add_column("memory_nodes", sa.Column("source_id", sa.String(length=128), nullable=True))
    op.add_column("memory_nodes", sa.Column("event_id", sa.String(length=128), nullable=True))
    op.create_index("ix_memory_nodes_source_type", "memory_nodes", ["source_type"])
    op.create_index("ix_memory_nodes_source_id", "memory_nodes", ["source_id"])
    op.create_index("ix_memory_nodes_event_id", "memory_nodes", ["event_id"])


def downgrade() -> None:
    """Drop source metadata columns and indexes"""
    op.drop_index("ix_memory_nodes_event_id", table_name="memory_nodes")
    op.drop_index("ix_memory_nodes_source_id", table_name="memory_nodes")
    op.drop_index("ix_memory_nodes_source_type", table_name="memory_nodes")
    op.drop_column("memory_nodes", "event_id")
    op.drop_column("memory_nodes", "source_id")
    op.drop_column("memory_nodes", "source_type")
