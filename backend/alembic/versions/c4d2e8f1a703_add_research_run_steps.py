"""Store per-step model routing and usage for orchestrated (Auto) research runs.

Revision ID: c4d2e8f1a703
Revises: b260109a6e01
"""

import sqlalchemy as sa
from alembic import op

revision = "c4d2e8f1a703"
down_revision = "b260109a6e01"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("research_runs", sa.Column("steps", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("research_runs", "steps")
