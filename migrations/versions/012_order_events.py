"""Durable events and Discord delivery state."""
from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = depends_on = None


def upgrade():
    op.create_table("outbox_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("guild_id", sa.BigInteger, sa.ForeignKey("guilds.id"), nullable=False),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_outbox_events_guild_id", "outbox_events", ["guild_id"])
    op.create_table("integration_jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("guild_id", sa.BigInteger, sa.ForeignKey("guilds.id"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("lease", sa.String(36)),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_error", sa.String(1000)),
    )
    op.create_index("ix_integration_jobs_guild_id", "integration_jobs", ["guild_id"])
    op.create_table("order_settings",
        sa.Column("guild_id", sa.BigInteger, sa.ForeignKey("guilds.id"), primary_key=True),
        sa.Column("panel_channel_id", sa.BigInteger),
        sa.Column("panel_message_id", sa.BigInteger),
        sa.Column("logistics_channel_id", sa.BigInteger),
        sa.Column("fallback_category_id", sa.BigInteger),
        sa.Column("panel_title", sa.String(100), nullable=False),
        sa.Column("panel_description", sa.String(2000), nullable=False),
        sa.Column("bot_last_seen", sa.DateTime(timezone=True)),
    )
    op.create_table("order_discord_messages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("order_id", sa.Integer, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("channel_id", sa.BigInteger, nullable=False),
        sa.Column("message_id", sa.BigInteger),
        sa.UniqueConstraint("order_id", "kind", name="uq_order_message"),
    )
    op.create_index("ix_order_discord_messages_order_id", "order_discord_messages", ["order_id"])


def downgrade():
    for name in ("order_discord_messages", "order_settings", "integration_jobs", "outbox_events"):
        op.drop_table(name)
