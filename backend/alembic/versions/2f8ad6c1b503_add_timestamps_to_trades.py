"""add created_at / updated_at to trades

Existing rows are backfilled with their trade_date, which is the closest thing to a
creation time we have for them.

Revision ID: 2f8ad6c1b503
Revises: 7c3f1a9d4e21
Create Date: 2026-09-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2f8ad6c1b503"
down_revision: str | None = "7c3f1a9d4e21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "trades",
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.add_column(
        "trades",
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    # updated_at is bumped by SQLAlchemy's onupdate, not a MySQL ON UPDATE clause, so the
    # schema stays portable if this moves to Postgres. Raw SQL updates won't touch it.
    # Rows that existed before this migration get their trade_date rather than "now",
    # so ordering by created_at stays meaningful for historical trades.
    op.execute("UPDATE trades SET created_at = trade_date, updated_at = trade_date")


def downgrade() -> None:
    op.drop_column("trades", "updated_at")
    op.drop_column("trades", "created_at")
