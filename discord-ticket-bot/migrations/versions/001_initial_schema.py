"""initial schema

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guilds",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "ticket_forms",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "form_fields",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("form_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=45), nullable=False),
        sa.Column("placeholder", sa.String(length=100), nullable=True),
        sa.Column("field_type", sa.String(length=50), nullable=False, server_default="text"),
        sa.Column("options", sa.JSON(), nullable=True),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("min_length", sa.Integer(), nullable=True),
        sa.Column("max_length", sa.Integer(), nullable=True),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.ForeignKeyConstraint(["form_id"], ["ticket_forms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "ticket_statuses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("color", sa.Integer(), nullable=False, server_default="5793266"),
        sa.Column("emoji", sa.String(length=50), nullable=True),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "ticket_panels",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("color", sa.Integer(), nullable=False, server_default="5793266"),
        sa.Column("category_id", sa.BigInteger(), nullable=True),
        sa.Column("form_id", sa.Integer(), nullable=True),
        sa.Column("button_label", sa.String(length=80), nullable=False, server_default="Создать заявку"),
        sa.Column("button_emoji", sa.String(length=50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["form_id"], ["ticket_forms.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("panel_id", sa.Integer(), nullable=True),
        sa.Column("form_id", sa.Integer(), nullable=True),
        sa.Column("status_id", sa.Integer(), nullable=True),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column("assignee_id", sa.BigInteger(), nullable=True),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("closed_by", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["form_id"], ["ticket_forms.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["panel_id"], ["ticket_panels.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["status_id"], ["ticket_statuses.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel_id"),
        sa.UniqueConstraint("guild_id", "number", name="uq_ticket_number"),
    )

    op.create_table(
        "ticket_responses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("field_id", sa.Integer(), nullable=True),
        sa.Column("field_label", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["field_id"], ["form_fields.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "staff_roles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("role_type", sa.String(length=20), nullable=False),
        sa.Column("panel_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["panel_id"], ["ticket_panels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("user_name", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_guild_id", "audit_logs", ["guild_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    op.create_table(
        "notification_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("notify_new_ticket", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("notify_status_change", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("notify_assignment", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("notify_close", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("dm_author_on_close", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id"),
    )

    op.create_table(
        "log_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_create", sa.BigInteger(), nullable=True),
        sa.Column("channel_close", sa.BigInteger(), nullable=True),
        sa.Column("channel_error", sa.BigInteger(), nullable=True),
        sa.Column("channel_admin", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id"),
    )

    op.create_index("ix_tickets_guild_id", "tickets", ["guild_id"])
    op.create_index("ix_tickets_channel_id", "tickets", ["channel_id"])
    op.create_index("ix_tickets_author_id", "tickets", ["author_id"])
    op.create_index("ix_tickets_is_closed", "tickets", ["is_closed"])


def downgrade() -> None:
    op.drop_table("log_settings")
    op.drop_table("notification_settings")
    op.drop_table("audit_logs")
    op.drop_table("staff_roles")
    op.drop_table("ticket_responses")
    op.drop_table("tickets")
    op.drop_table("ticket_panels")
    op.drop_table("ticket_statuses")
    op.drop_table("form_fields")
    op.drop_table("ticket_forms")
    op.drop_table("guilds")
