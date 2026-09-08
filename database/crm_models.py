from datetime import datetime
import uuid

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, String, func, Integer, JSON, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models import Base


def new_id() -> str:
    return str(uuid.uuid4())


class ApiCredential(Base):
    __tablename__ = "api_credentials"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (CheckConstraint(
        "role IN ('ADMIN','MANAGER','LOGISTICIAN','PRODUCTION','DELIVERY','VIEWER','BOT')",
        name="ck_credential_role",
    ),)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id"), index=True)
    public_number: Mapped[int] = mapped_column(Integer)
    discord_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    customer_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(24), default="NEW", index=True)
    assigned_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    delivery_location: Mapped[str] = mapped_column(String(300))
    comment: Mapped[str] = mapped_column(Text, default="")
    idempotency_key: Mapped[str] = mapped_column(String(36))
    request_hash: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    items: Mapped[list["OrderItem"]] = relationship(cascade="all, delete-orphan", order_by="OrderItem.position")
    __table_args__ = (
        UniqueConstraint("guild_id", "public_number", name="uq_order_number"),
        UniqueConstraint("guild_id", "discord_user_id", "idempotency_key", name="uq_order_request"),
        CheckConstraint("version > 0", name="ck_order_version"),
        CheckConstraint("status IN ('NEW','ACCEPTED','WAITING_RESOURCES','IN_PRODUCTION','READY','IN_DELIVERY','COMPLETED','CANCELLED','REJECTED','ON_HOLD')", name="ck_order_status"),
    )


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("foxhole_items.id", ondelete="SET NULL"), nullable=True)
    api_id_snapshot: Mapped[str | None] = mapped_column(String(200), nullable=True)
    name_snapshot: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(20))
    position: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    unit: Mapped[str] = mapped_column(String(20))
    comment: Mapped[str] = mapped_column(Text, default="")
    calculation: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (
        CheckConstraint("quantity > 0 AND quantity <= 100000", name="ck_order_item_quantity"),
        CheckConstraint("unit IN ('item','crate','batch','request')", name="ck_order_item_unit"),
    )


class OrderNote(Base):
    __tablename__ = "order_notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(BigInteger)
    author_name: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id"), index=True)
    kind: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IntegrationJob(Base):
    __tablename__ = "integration_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease: Mapped[str | None] = mapped_column(String(36), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class OrderSettings(Base):
    __tablename__ = "order_settings"
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id"), primary_key=True)
    panel_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    panel_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    logistics_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fallback_category_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    panel_title: Mapped[str] = mapped_column(String(100), default="Логистический центр")
    panel_description: Mapped[str] = mapped_column(String(2000), default="Оставьте заявку на технику, припасы или доставку.")
    bot_last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OrderDiscordMessage(Base):
    __tablename__ = "order_discord_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey("orders.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    channel_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    __table_args__ = (UniqueConstraint("order_id", "kind", name="uq_order_message"),)


class PermissionBinding(Base):
    __tablename__ = "permission_bindings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id"), index=True)
    discord_role_id: Mapped[int] = mapped_column(BigInteger)
    app_role: Mapped[str] = mapped_column(String(20))
    __table_args__ = (
        UniqueConstraint("guild_id", "discord_role_id", name="uq_crm_role_binding"),
        CheckConstraint("app_role IN ('ADMIN','MANAGER','LOGISTICIAN','PRODUCTION','DELIVERY','VIEWER')", name="ck_binding_role"),
    )
