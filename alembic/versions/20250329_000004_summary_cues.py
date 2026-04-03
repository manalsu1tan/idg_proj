from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20250329_000004"
down_revision = "20250323_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("memory_nodes", sa.Column("retrieval_cue", sa.Text(), nullable=False, server_default=""))
    op.add_column("memory_nodes", sa.Column("answer_cue", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("memory_nodes", "answer_cue")
    op.drop_column("memory_nodes", "retrieval_cue")
