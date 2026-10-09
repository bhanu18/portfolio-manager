"""Persist research provider selection; existing runs remain OpenAI.

Revision ID: b260109a6e01
Revises: a913ed042d10
"""

import sqlalchemy as sa
from alembic import op

revision = "b260109a6e01"
down_revision = "a913ed042d10"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "research_runs",
        sa.Column("provider", sa.String(20), nullable=False, server_default="openai"),
    )


def downgrade():
    op.drop_column("research_runs", "provider")
