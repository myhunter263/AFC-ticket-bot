"""add calculator recipe metadata and overrides

Revision ID: 009
Revises: 008
"""

from alembic import op
import sqlalchemy as sa


revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("foxhole_items", sa.Column("image_url", sa.String(length=500), nullable=True))
    op.add_column("foxhole_production_recipes", sa.Column("building", sa.String(length=100), nullable=True))
    op.add_column(
        "foxhole_production_recipes",
        sa.Column("recipe_kind", sa.String(length=30), nullable=False, server_default="standard"),
    )
    op.add_column(
        "foxhole_production_recipes",
        sa.Column("source", sa.String(length=50), nullable=False, server_default="foxholehq"),
    )
    op.add_column(
        "foxhole_production_recipes",
        sa.Column("source_version", sa.String(length=100), nullable=True),
    )
    op.create_table(
        "foxhole_recipe_overrides",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("production_method", sa.String(length=50), nullable=False),
        sa.Column("building", sa.String(length=100), nullable=True),
        sa.Column("materials", sa.JSON(), nullable=False),
        sa.Column("output_quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("output_unit", sa.String(length=20), nullable=False, server_default="item"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["foxhole_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "guild_id", "item_id", "production_method",
            name="uq_foxhole_recipe_override",
        ),
    )
    op.create_index("ix_foxhole_recipe_overrides_guild_id", "foxhole_recipe_overrides", ["guild_id"])
    op.create_index("ix_foxhole_recipe_overrides_item_id", "foxhole_recipe_overrides", ["item_id"])


def downgrade() -> None:
    op.drop_table("foxhole_recipe_overrides")
    op.drop_column("foxhole_production_recipes", "source_version")
    op.drop_column("foxhole_production_recipes", "source")
    op.drop_column("foxhole_production_recipes", "recipe_kind")
    op.drop_column("foxhole_production_recipes", "building")
    op.drop_column("foxhole_items", "image_url")
