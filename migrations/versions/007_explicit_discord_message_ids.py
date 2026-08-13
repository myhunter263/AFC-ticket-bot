"""Use explicit names for persistent Discord channel and message identifiers.

Revision ID: 007
Revises: 006
"""

from alembic import op


revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "ticket_panels",
        "channel_id",
        new_column_name="panel_channel_id",
    )
    op.alter_column(
        "ticket_panels",
        "message_id",
        new_column_name="panel_message_id",
    )
    op.alter_column(
        "tickets",
        "message_id",
        new_column_name="ticket_message_id",
    )
    op.alter_column(
        "tickets",
        "channel_id",
        new_column_name="ticket_channel_id",
    )


def downgrade() -> None:
    op.alter_column(
        "tickets",
        "ticket_channel_id",
        new_column_name="channel_id",
    )
    op.alter_column(
        "tickets",
        "ticket_message_id",
        new_column_name="message_id",
    )
    op.alter_column(
        "ticket_panels",
        "panel_message_id",
        new_column_name="message_id",
    )
    op.alter_column(
        "ticket_panels",
        "panel_channel_id",
        new_column_name="channel_id",
    )
