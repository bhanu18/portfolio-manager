"""Create appointments table for Express Tailoring

Revision ID: a1b2c3d4e5f6
Revises: b46451958cb3
Create Date: 2025-01-21 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'b46451958cb3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create appointments table for Express Tailoring booking system."""
    # Create enum types first
    express_service_enum = sa.Enum(
        'hem_pants', 'shorten_sleeves', 'take_in_waist', 'take_in_sides',
        'button_replacement', 'zipper_repair', 'emergency_repair',
        'express_custom_shirt', 'other',
        name='express_service_enum'
    )

    appointment_status_enum = sa.Enum(
        'pending', 'confirmed', 'cancelled', 'completed',
        name='appointment_status_enum'
    )

    # Create the appointments table
    op.create_table(
        'appointments',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('booking_reference', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=False),
        sa.Column('date', sa.DateTime(), nullable=False),
        sa.Column('time_slot', sa.String(length=20), nullable=False),
        sa.Column('estimated_end_time', sa.String(length=20), nullable=True),
        sa.Column('express_service', express_service_enum, nullable=False),
        sa.Column('garment_details', sa.String(length=500), nullable=True),
        sa.Column('special_requests', sa.String(length=500), nullable=True),
        sa.Column('status', appointment_status_enum, nullable=False, server_default='pending'),
        sa.Column('admin_notes', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for efficient querying
    op.create_index(op.f('ix_appointments_id'), 'appointments', ['id'], unique=False)
    op.create_index(op.f('ix_appointments_booking_reference'), 'appointments', ['booking_reference'], unique=True)
    op.create_index(op.f('ix_appointments_email'), 'appointments', ['email'], unique=False)
    op.create_index(op.f('ix_appointments_date'), 'appointments', ['date'], unique=False)


def downgrade() -> None:
    """Remove appointments table."""
    # Drop indexes
    op.drop_index(op.f('ix_appointments_date'), table_name='appointments')
    op.drop_index(op.f('ix_appointments_email'), table_name='appointments')
    op.drop_index(op.f('ix_appointments_booking_reference'), table_name='appointments')
    op.drop_index(op.f('ix_appointments_id'), table_name='appointments')

    # Drop the table
    op.drop_table('appointments')

    # Drop enum types
    sa.Enum(name='express_service_enum').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='appointment_status_enum').drop(op.get_bind(), checkfirst=True)
