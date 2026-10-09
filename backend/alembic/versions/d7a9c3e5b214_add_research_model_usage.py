"""Aggregate research token usage per model per UTC day.

Revision ID: d7a9c3e5b214
Revises: c4d2e8f1a703
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

TIMESTAMP = sa.DateTime().with_variant(DATETIME(fsp=6), "mysql")

revision = "d7a9c3e5b214"
down_revision = "c4d2e8f1a703"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "research_model_usage",
        sa.Column("day", sa.String(10), primary_key=True),
        sa.Column("provider", sa.String(20), primary_key=True),
        sa.Column("model", sa.String(100), primary_key=True),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
    )


def downgrade():
    op.drop_table("research_model_usage")
