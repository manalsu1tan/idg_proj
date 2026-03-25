from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20250320_000002"
down_revision = "20250317_000001"
branch_labels = None
depends_on = None


def _index_names(bind, table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def _foreign_key_names(bind, table_name: str) -> set[str]:
    return {fk["name"] for fk in sa.inspect(bind).get_foreign_keys(table_name) if fk.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    index_names = _index_names(bind, "memory_edges")

    if "ix_memory_edges_parent_type_child" not in index_names:
        op.create_index(
            "ix_memory_edges_parent_type_child",
            "memory_edges",
            ["parent_id", "edge_type", "child_id"],
            unique=False,
        )
    if "ix_memory_edges_child_type_parent" not in index_names:
        op.create_index(
            "ix_memory_edges_child_type_parent",
            "memory_edges",
            ["child_id", "edge_type", "parent_id"],
            unique=False,
        )

    if bind.dialect.name != "sqlite":
        foreign_key_names = _foreign_key_names(bind, "memory_edges")
        if "fk_memory_edges_parent" not in foreign_key_names:
            op.create_foreign_key(
                "fk_memory_edges_parent",
                "memory_edges",
                "memory_nodes",
                ["parent_id"],
                ["node_id"],
                ondelete="CASCADE",
            )
        if "fk_memory_edges_child" not in foreign_key_names:
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

    index_names = _index_names(bind, "memory_edges")
    if "ix_memory_edges_child_type_parent" in index_names:
        op.drop_index("ix_memory_edges_child_type_parent", table_name="memory_edges")
    if "ix_memory_edges_parent_type_child" in index_names:
        op.drop_index("ix_memory_edges_parent_type_child", table_name="memory_edges")
