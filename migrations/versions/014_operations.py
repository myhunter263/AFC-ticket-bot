"""Warehouses, transactional reservations and order production tasks."""
from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
branch_labels = depends_on = None


def upgrade():
    op.create_table("warehouses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("guild_id", sa.BigInteger, sa.ForeignKey("guilds.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.UniqueConstraint("guild_id", "name", name="uq_warehouse_name"))
    op.create_index("ix_warehouses_guild_id", "warehouses", ["guild_id"])
    op.create_table("stock_balances",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("warehouse_id", sa.Integer, sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("foxhole_items.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("unit", sa.String(10), nullable=False),
        sa.Column("actual", sa.Integer, nullable=False),
        sa.Column("reserved", sa.Integer, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.UniqueConstraint("warehouse_id", "item_id", "unit", name="uq_stock_item_unit"),
        sa.CheckConstraint("actual >= 0 AND reserved >= 0 AND reserved <= actual", name="ck_stock_counts"),
        sa.CheckConstraint("unit IN ('item','crate')", name="ck_stock_unit"),
        sa.CheckConstraint("version > 0", name="ck_stock_version"))
    op.create_index("ix_stock_balances_warehouse_id", "stock_balances", ["warehouse_id"])
    op.create_table("stock_reservations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_id", sa.Integer, sa.ForeignKey("stock_balances.id"), nullable=False),
        sa.Column("order_id", sa.Integer, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("created_by", sa.BigInteger, nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("order_id", "request_key", name="uq_reservation_request"),
        sa.CheckConstraint("quantity > 0", name="ck_reservation_quantity"),
        sa.CheckConstraint("state IN ('ACTIVE','RELEASED','CONSUMED')", name="ck_reservation_state"),
        sa.CheckConstraint("version > 0", name="ck_reservation_version"))
    for name in ("stock_id", "order_id"):
        op.create_index(f"ix_stock_reservations_{name}", "stock_reservations", [name])
    op.create_table("production_tasks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("order_id", sa.Integer, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("completed", sa.Integer, nullable=False),
        sa.Column("unit", sa.String(10), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("assigned_user_id", sa.BigInteger),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("order_id", "request_key", name="uq_production_request"),
        sa.CheckConstraint("quantity > 0 AND completed >= 0 AND completed <= quantity", name="ck_production_counts"),
        sa.CheckConstraint("status IN ('PLANNED','IN_PROGRESS','COMPLETED','CANCELLED')", name="ck_production_status"),
        sa.CheckConstraint("unit IN ('item','crate','batch')", name="ck_production_unit"),
        sa.CheckConstraint("version > 0", name="ck_production_version"))
    op.create_index("ix_production_tasks_order_id", "production_tasks", ["order_id"])


def downgrade():
    for name in ("production_tasks", "stock_reservations", "stock_balances", "warehouses"):
        op.drop_table(name)
