from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20250320_000002"
down_revision = "20250317_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    op.create_index(
        "ix_memory_edges_parent_type_child",
        "memory_edges",
        ["parent_id", "edge_type", "child_id"],
        unique=False,
    )
    op.create_index(
        "ix_memory_edges_child_type_parent",
        "memory_edges",
        ["child_id", "edge_type", "parent_id"],
        unique=False,
    )

    op.create_foreign_key(
        "fk_memory_edges_parent",
        "memory_edges",
        "memory_nodes",
        ["parent_id"],
        ["node_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_memory_edges_child",
        "memory_edges",
        "memory_nodes",
        ["child_id"],
        ["node_id"],
        ondelete="CASCADE",
    )

    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_memory_nodes_agent_level_active_time "
            "ON memory_nodes (agent_id, level, timestamp_end DESC) WHERE stale_flag = false"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_memory_nodes_embedding_hnsw "
            "ON memory_nodes USING hnsw (embedding vector_cosine_ops)"
        )


def downgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_memory_nodes_embedding_hnsw")
        op.execute("DROP INDEX IF EXISTS ix_memory_nodes_agent_level_active_time")

    op.drop_constraint("fk_memory_edges_child", "memory_edges", type_="foreignkey")
    op.drop_constraint("fk_memory_edges_parent", "memory_edges", type_="foreignkey")
    op.drop_index("ix_memory_edges_child_type_parent", table_name="memory_edges")
    op.drop_index("ix_memory_edges_parent_type_child", table_name="memory_edges")
