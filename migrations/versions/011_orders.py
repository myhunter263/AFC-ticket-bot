"""Independent CRM orders; legacy tickets remain untouched."""
from alembic import op
import sqlalchemy as sa

revision = "011"
down_revision = "010"
branch_labels = depends_on = None


def upgrade():
    op.create_table("orders",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("guild_id", sa.BigInteger, sa.ForeignKey("guilds.id"), nullable=False),
        sa.Column("public_number", sa.Integer, nullable=False),
        sa.Column("discord_user_id", sa.BigInteger, nullable=False),
        sa.Column("customer_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("assigned_user_id", sa.BigInteger),
        sa.Column("delivery_location", sa.String(300), nullable=False),
        sa.Column("comment", sa.Text, nullable=False),
        sa.Column("idempotency_key", sa.String(36), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("guild_id", "public_number", name="uq_order_number"),
        sa.UniqueConstraint("guild_id", "discord_user_id", "idempotency_key", name="uq_order_request"),
        sa.CheckConstraint("version > 0", name="ck_order_version"),
        sa.CheckConstraint("status IN ('NEW','ACCEPTED','WAITING_RESOURCES','IN_PRODUCTION','READY','IN_DELIVERY','COMPLETED','CANCELLED','REJECTED','ON_HOLD')", name="ck_order_status"),
    )
    for field in ("guild_id", "discord_user_id", "status", "assigned_user_id"):
        op.create_index(f"ix_orders_{field}", "orders", [field])
    op.create_table("order_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("order_id", sa.Integer, sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("foxhole_items.id", ondelete="SET NULL")),
        sa.Column("api_id_snapshot", sa.String(200)),
        sa.Column("name_snapshot", sa.String(200), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("comment", sa.Text, nullable=False),
        sa.Column("calculation", sa.JSON, nullable=False),
        sa.CheckConstraint("quantity > 0 AND quantity <= 100000", name="ck_order_item_quantity"),
        sa.CheckConstraint("unit IN ('item','crate','batch','request')", name="ck_order_item_unit"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_table("order_notes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("order_id", sa.Integer, sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.BigInteger, nullable=False),
        sa.Column("author_name", sa.String(100), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_order_notes_order_id", "order_notes", ["order_id"])
    op.create_index("ix_audit_logs_object", "audit_logs", ["guild_id", "target_type", "target_id", "created_at"])


def downgrade():
    op.drop_index("ix_audit_logs_object", table_name="audit_logs")
    op.drop_table("order_notes")
    op.drop_table("order_items")
    op.drop_table("orders")
