"""Add private research history and durable jobs.

Revision ID: a913ed042d10
Revises: 2f8ad6c1b503
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME

TIMESTAMP = sa.DateTime().with_variant(DATETIME(fsp=6), "mysql")

revision = "a913ed042d10"
down_revision = "2f8ad6c1b503"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "research_daily_usage",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("day", sa.String(10), primary_key=True),
        sa.Column("runs", sa.Integer(), nullable=False),
    )
    op.create_table(
        "research_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
    )
    op.create_index("ix_research_sessions_user_id", "research_sessions", ["user_id"])
    op.create_table(
        "research_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("research_sessions.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stage", sa.String(160), nullable=False),
        sa.Column("report", sa.Text(), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("model_turns", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("worker_id", sa.String(36), nullable=True),
        sa.Column("lease_expires_at", TIMESTAMP, nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("started_at", TIMESTAMP, nullable=True),
        sa.Column("finished_at", TIMESTAMP, nullable=True),
        sa.UniqueConstraint("session_id", "request_id", name="uq_research_request"),
    )
    op.create_index("ix_research_runs_user_id", "research_runs", ["user_id"])
    op.create_index("ix_research_runs_session_id", "research_runs", ["session_id"])
    op.create_index("ix_research_queue", "research_runs", ["status", "created_at"])
    op.create_table(
        "research_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("research_sessions.id"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("research_runs.id"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
    )
    op.create_index("ix_research_messages_session_id", "research_messages", ["session_id"])
    op.create_index("ix_research_messages_run_id", "research_messages", ["run_id"])


def downgrade():
    op.drop_table("research_messages")
    op.drop_table("research_runs")
    op.drop_table("research_sessions")
    op.drop_table("research_daily_usage")
