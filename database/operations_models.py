"""Application-owned stock and production state; item definitions stay in the shared cache."""
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database.models import Base


class Warehouse(Base):
    __tablename__ = "warehouses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    __table_args__ = (UniqueConstraint("guild_id", "name", name="uq_warehouse_name"),)


class Stock(Base):
    __tablename__ = "stock_balances"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("foxhole_items.id"))
    name: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(10))
    actual: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        UniqueConstraint("warehouse_id", "item_id", "unit", name="uq_stock_item_unit"),
        CheckConstraint("actual >= 0 AND reserved >= 0 AND reserved <= actual", name="ck_stock_counts"),
        CheckConstraint("unit IN ('item','crate')", name="ck_stock_unit"),
        CheckConstraint("version > 0", name="ck_stock_version"),
    )


class Reservation(Base):
    __tablename__ = "stock_reservations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stock_balances.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    created_by: Mapped[int] = mapped_column(BigInteger)
    request_key: Mapped[str] = mapped_column(String(36))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("order_id", "request_key", name="uq_reservation_request"),
        CheckConstraint("quantity > 0", name="ck_reservation_quantity"),
        CheckConstraint("state IN ('ACTIVE','RELEASED','CONSUMED')", name="ck_reservation_state"),
        CheckConstraint("version > 0", name="ck_reservation_version"),
    )


class ProductionTask(Base):
    __tablename__ = "production_tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    unit: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(16), default="PLANNED")
    assigned_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    request_key: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("order_id", "request_key", name="uq_production_request"),
        CheckConstraint("quantity > 0 AND completed >= 0 AND completed <= quantity", name="ck_production_counts"),
        CheckConstraint("status IN ('PLANNED','IN_PROGRESS','COMPLETED','CANCELLED')", name="ck_production_status"),
        CheckConstraint("unit IN ('item','crate','batch')", name="ck_production_unit"),
        CheckConstraint("version > 0", name="ck_production_version"),
    )
