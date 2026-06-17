from __future__ import annotations

import datetime
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Guild(Base):
    __tablename__ = "guilds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    panels: Mapped[List["TicketPanel"]] = relationship(back_populates="guild", cascade="all, delete-orphan")
    forms: Mapped[List["TicketForm"]] = relationship(back_populates="guild", cascade="all, delete-orphan")
    statuses: Mapped[List["TicketStatus"]] = relationship(back_populates="guild", cascade="all, delete-orphan")
    tickets: Mapped[List["Ticket"]] = relationship(back_populates="guild", cascade="all, delete-orphan")
    staff_roles: Mapped[List["StaffRole"]] = relationship(back_populates="guild", cascade="all, delete-orphan")
    audit_logs: Mapped[List["AuditLog"]] = relationship(back_populates="guild", cascade="all, delete-orphan")
    notification_settings: Mapped[Optional["NotificationSettings"]] = relationship(
        back_populates="guild", cascade="all, delete-orphan", uselist=False
    )
    log_settings: Mapped[Optional["LogSettings"]] = relationship(
        back_populates="guild", cascade="all, delete-orphan", uselist=False
    )


class TicketPanel(Base):
    __tablename__ = "ticket_panels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    channel_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    color: Mapped[int] = mapped_column(Integer, default=0x5865F2)
    category_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    form_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("ticket_forms.id", ondelete="SET NULL"), nullable=True
    )
    button_label: Mapped[str] = mapped_column(String(80), default="Создать заявку")
    button_emoji: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    guild: Mapped["Guild"] = relationship(back_populates="panels")
    form: Mapped[Optional["TicketForm"]] = relationship(back_populates="panels")
    tickets: Mapped[List["Ticket"]] = relationship(back_populates="panel", cascade="all, delete-orphan")
    staff_roles: Mapped[List["StaffRole"]] = relationship(back_populates="panel", cascade="all, delete-orphan")


class TicketForm(Base):
    __tablename__ = "ticket_forms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    guild: Mapped["Guild"] = relationship(back_populates="forms")
    fields: Mapped[List["FormField"]] = relationship(
        back_populates="form", cascade="all, delete-orphan", order_by="FormField.order"
    )
    panels: Mapped[List["TicketPanel"]] = relationship(back_populates="form")
    tickets: Mapped[List["Ticket"]] = relationship(back_populates="form")


class FormField(Base):
    __tablename__ = "form_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    form_id: Mapped[int] = mapped_column(Integer, ForeignKey("ticket_forms.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(45))
    placeholder: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    field_type: Mapped[str] = mapped_column(String(50), default="text")
    options: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)
    min_length: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_length: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    form: Mapped["TicketForm"] = relationship(back_populates="fields")
    responses: Mapped[List["TicketResponse"]] = relationship(back_populates="field")


class TicketStatus(Base):
    __tablename__ = "ticket_statuses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(50))
    color: Mapped[int] = mapped_column(Integer, default=0x5865F2)
    emoji: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)

    guild: Mapped["Guild"] = relationship(back_populates="statuses")
    tickets: Mapped[List["Ticket"]] = relationship(back_populates="status")


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    panel_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("ticket_panels.id", ondelete="SET NULL"), nullable=True
    )
    form_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("ticket_forms.id", ondelete="SET NULL"), nullable=True
    )
    status_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("ticket_statuses.id", ondelete="SET NULL"), nullable=True
    )
    channel_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    author_id: Mapped[int] = mapped_column(BigInteger)
    assignee_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    number: Mapped[int] = mapped_column(Integer)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    closed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    closed_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (UniqueConstraint("guild_id", "number", name="uq_ticket_number"),)

    guild: Mapped["Guild"] = relationship(back_populates="tickets")
    panel: Mapped[Optional["TicketPanel"]] = relationship(back_populates="tickets")
    form: Mapped[Optional["TicketForm"]] = relationship(back_populates="tickets")
    status: Mapped[Optional["TicketStatus"]] = relationship(back_populates="tickets")
    responses: Mapped[List["TicketResponse"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan"
    )


class TicketResponse(Base):
    __tablename__ = "ticket_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"))
    field_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("form_fields.id", ondelete="SET NULL"), nullable=True
    )
    field_label: Mapped[str] = mapped_column(String(100))
    value: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    ticket: Mapped["Ticket"] = relationship(back_populates="responses")
    field: Mapped[Optional["FormField"]] = relationship(back_populates="responses")


class StaffRole(Base):
    __tablename__ = "staff_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    role_id: Mapped[int] = mapped_column(BigInteger)
    role_type: Mapped[str] = mapped_column(String(20))  # admin, moderator, operator
    panel_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("ticket_panels.id", ondelete="CASCADE"), nullable=True
    )

    guild: Mapped["Guild"] = relationship(back_populates="staff_roles")
    panel: Mapped[Optional["TicketPanel"]] = relationship(back_populates="staff_roles")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger)
    user_name: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    target_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    guild: Mapped["Guild"] = relationship(back_populates="audit_logs")


class NotificationSettings(Base):
    __tablename__ = "notification_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), unique=True)
    notify_new_ticket: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_status_change: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_assignment: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_close: Mapped[bool] = mapped_column(Boolean, default=True)
    dm_author_on_close: Mapped[bool] = mapped_column(Boolean, default=False)

    guild: Mapped["Guild"] = relationship(back_populates="notification_settings")


class LogSettings(Base):
    __tablename__ = "log_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), unique=True)
    channel_create: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    channel_close: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    channel_error: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    channel_admin: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    guild: Mapped["Guild"] = relationship(back_populates="log_settings")
