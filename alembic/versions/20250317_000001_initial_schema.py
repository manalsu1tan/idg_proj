from __future__ import annotations

"""Initial storage schema
Creates the base memory graph and trace tables"""

from alembic import op
import sqlalchemy as sa

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # pragma: no cover
    Vector = None


revision = "20250317_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the initial schema"""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    embedding_type = Vector(12) if bind.dialect.name == "postgresql" and Vector is not None else sa.Text()

    op.create_table(
        "memory_nodes",
        sa.Column("node_id", sa.String(length=64), primary_key=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.Column("node_type", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("timestamp_start", sa.DateTime(), nullable=False),
        sa.Column("timestamp_end", sa.DateTime(), nullable=False),
        sa.Column("parent_ids", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("child_ids", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("support_ids", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("embedding", embedding_type, nullable=True),
        sa.Column("importance_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("recency_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("relevance_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_accessed_at", sa.DateTime(), nullable=True),
        sa.Column("entities", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("topics", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("stale_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("summary_policy_id", sa.String(length=64), nullable=True),
        sa.Column("quality_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("quality_scores", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_hash", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(length=32), nullable=False, server_default="system"),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("model_version", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_memory_nodes_agent_id", "memory_nodes", ["agent_id"])
    op.create_index("ix_memory_nodes_level", "memory_nodes", ["level"])
    op.create_index("ix_memory_nodes_timestamp_start", "memory_nodes", ["timestamp_start"])
    op.create_index("ix_memory_nodes_timestamp_end", "memory_nodes", ["timestamp_end"])
    op.create_index("ix_memory_nodes_stale_flag", "memory_nodes", ["stale_flag"])

    op.create_table(
        "memory_edges",
        sa.Column("edge_id", sa.String(length=64), primary_key=True),
        sa.Column("parent_id", sa.String(length=64), nullable=False),
        sa.Column("child_id", sa.String(length=64), nullable=False),
        sa.Column("edge_type", sa.String(length=32), nullable=False),
    )
    op.create_index("ix_memory_edges_parent_id", "memory_edges", ["parent_id"])
    op.create_index("ix_memory_edges_child_id", "memory_edges", ["child_id"])
    op.create_index("ix_memory_edges_edge_type", "memory_edges", ["edge_type"])

    op.create_table(
        "eval_runs",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("scenario_name", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
    )
    op.create_index("ix_eval_runs_scenario_name", "eval_runs", ["scenario_name"])

    op.create_table(
        "retrieval_traces",
        sa.Column("trace_id", sa.String(length=64), primary_key=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("token_budget", sa.Integer(), nullable=False),
        sa.Column("retrieval_depth", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
    )
    op.create_index("ix_retrieval_traces_agent_id", "retrieval_traces", ["agent_id"])
    op.create_index("ix_retrieval_traces_mode", "retrieval_traces", ["mode"])
    op.create_index("ix_retrieval_traces_created_at", "retrieval_traces", ["created_at"])

    op.create_table(
        "model_traces",
        sa.Column("trace_id", sa.String(length=64), primary_key=True),
        sa.Column("node_id", sa.String(length=64), nullable=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("component", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("request_payload", sa.Text(), nullable=False),
        sa.Column("response_payload", sa.Text(), nullable=False),
    )
    op.create_index("ix_model_traces_agent_id", "model_traces", ["agent_id"])
    op.create_index("ix_model_traces_node_id", "model_traces", ["node_id"])
    op.create_index("ix_model_traces_component", "model_traces", ["component"])
    op.create_index("ix_model_traces_provider", "model_traces", ["provider"])
    op.create_index("ix_model_traces_created_at", "model_traces", ["created_at"])


def downgrade() -> None:
    """Drop the initial schema"""
    op.drop_index("ix_model_traces_created_at", table_name="model_traces")
    op.drop_index("ix_model_traces_provider", table_name="model_traces")
    op.drop_index("ix_model_traces_component", table_name="model_traces")
    op.drop_index("ix_model_traces_node_id", table_name="model_traces")
    op.drop_index("ix_model_traces_agent_id", table_name="model_traces")
    op.drop_table("model_traces")

    op.drop_index("ix_retrieval_traces_created_at", table_name="retrieval_traces")
    op.drop_index("ix_retrieval_traces_mode", table_name="retrieval_traces")
    op.drop_index("ix_retrieval_traces_agent_id", table_name="retrieval_traces")
    op.drop_table("retrieval_traces")

    op.drop_index("ix_eval_runs_scenario_name", table_name="eval_runs")
    op.drop_table("eval_runs")

    op.drop_index("ix_memory_edges_edge_type", table_name="memory_edges")
    op.drop_index("ix_memory_edges_child_id", table_name="memory_edges")
    op.drop_index("ix_memory_edges_parent_id", table_name="memory_edges")
    op.drop_table("memory_edges")

    op.drop_index("ix_memory_nodes_stale_flag", table_name="memory_nodes")
    op.drop_index("ix_memory_nodes_timestamp_end", table_name="memory_nodes")
    op.drop_index("ix_memory_nodes_timestamp_start", table_name="memory_nodes")
    op.drop_index("ix_memory_nodes_level", table_name="memory_nodes")
    op.drop_index("ix_memory_nodes_agent_id", table_name="memory_nodes")
    op.drop_table("memory_nodes")
