"""add self-role and recruitment modules

Revision ID: 008
Revises: 007
"""

from alembic import op
import sqlalchemy as sa


revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "role_panels",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("panel_channel_id", sa.BigInteger(), nullable=False),
        sa.Column("panel_message_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("color", sa.Integer(), nullable=False, server_default="5793266"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_role_panels_guild_id", "role_panels", ["guild_id"])

    op.create_table(
        "role_panel_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("panel_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("emoji", sa.String(length=100), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("rules", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["panel_id"], ["role_panels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("panel_id", "role_id", name="uq_role_panel_role"),
    )
    op.create_index("ix_role_panel_items_panel_id", "role_panel_items", ["panel_id"])

    op.create_table(
        "recruitment_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("panel_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("panel_message_id", sa.BigInteger(), nullable=True),
        sa.Column("ticket_category_id", sa.BigInteger(), nullable=True),
        sa.Column("accepted_role_id", sa.BigInteger(), nullable=True),
        sa.Column("panel_title", sa.String(length=100), nullable=False, server_default="Вступление в клан"),
        sa.Column("panel_description", sa.Text(), nullable=True),
        sa.Column("button_label", sa.String(length=80), nullable=False, server_default="Подать заявку"),
        sa.Column("button_emoji", sa.String(length=100), nullable=True),
        sa.Column("channel_name_template", sa.String(length=100), nullable=False, server_default="recruit-{application_id}"),
        sa.Column("allow_multiple_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("guild_id"),
    )

    op.create_table(
        "recruitment_questions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("settings_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=45), nullable=False),
        sa.Column("placeholder", sa.String(length=100), nullable=True),
        sa.Column("input_style", sa.String(length=20), nullable=False, server_default="short"),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("min_length", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_length", sa.Integer(), nullable=False, server_default="1024"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["settings_id"], ["recruitment_settings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recruitment_questions_settings_id", "recruitment_questions", ["settings_id"])

    op.create_table(
        "recruitment_staff_roles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("settings_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["settings_id"], ["recruitment_settings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("settings_id", "role_id", name="uq_recruitment_staff_role"),
    )
    op.create_index("ix_recruitment_staff_roles_settings_id", "recruitment_staff_roles", ["settings_id"])

    op.create_table(
        "recruitment_applications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("ticket_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("ticket_message_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("reviewer_id", sa.BigInteger(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("answers", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticket_channel_id"),
    )
    op.create_index("ix_recruitment_applications_guild_id", "recruitment_applications", ["guild_id"])
    op.create_index("ix_recruitment_applications_user_id", "recruitment_applications", ["user_id"])
    op.create_index("ix_recruitment_applications_status", "recruitment_applications", ["status"])


def downgrade() -> None:
    op.drop_table("recruitment_applications")
    op.drop_table("recruitment_staff_roles")
    op.drop_table("recruitment_questions")
    op.drop_table("recruitment_settings")
    op.drop_table("role_panel_items")
    op.drop_table("role_panels")
