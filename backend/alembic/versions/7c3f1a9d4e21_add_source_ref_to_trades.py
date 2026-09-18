"""add source_ref to trades for idempotent imports

Revision ID: 7c3f1a9d4e21
Revises: b46451958cb3
Create Date: 2026-09-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c3f1a9d4e21"
down_revision: str | None = "b46451958cb3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trades", sa.Column("source_ref", sa.String(length=64), nullable=True))
    op.create_index("uq_trades_source_ref", "trades", ["source_ref"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_trades_source_ref", table_name="trades")
    op.drop_column("trades", "source_ref")
