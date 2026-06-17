from __future__ import annotations

import datetime
import logging
from typing import Optional

import discord
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    Guild,
    LogSettings,
    NotificationSettings,
    Ticket,
    TicketPanel,
    TicketResponse,
    TicketStatus,
)
from services.status_service import StatusService

logger = logging.getLogger(__name__)


class TicketService:

    @staticmethod
    async def get_or_create_guild(session: AsyncSession, guild: discord.Guild) -> Guild:
        result = await session.execute(
            select(Guild).where(Guild.id == guild.id)
        )
        db_guild = result.scalar_one_or_none()
        if not db_guild:
            db_guild = Guild(id=guild.id, name=guild.name)
            session.add(db_guild)
            await session.flush()
            await StatusService.ensure_defaults(session, guild.id)
        return db_guild

    @staticmethod
    async def get_next_ticket_number(session: AsyncSession, guild_id: int) -> int:
        result = await session.execute(
            select(func.max(Ticket.number)).where(Ticket.guild_id == guild_id)
        )
        max_num = result.scalar_one_or_none()
        return (max_num or 0) + 1

    @staticmethod
    async def count_open_by_user(
        session: AsyncSession, guild_id: int, user_id: int
    ) -> int:
        result = await session.execute(
            select(func.count(Ticket.id)).where(
                Ticket.guild_id == guild_id,
                Ticket.author_id == user_id,
                Ticket.is_closed == False,
            )
        )
        return result.scalar_one()

    @staticmethod
    async def create_ticket(
        session: AsyncSession,
        guild_id: int,
        panel_id: int,
        form_id: Optional[int],
        channel_id: int,
        author_id: int,
        status_id: int,
    ) -> Ticket:
        number = await TicketService.get_next_ticket_number(session, guild_id)
        ticket = Ticket(
            guild_id=guild_id,
            panel_id=panel_id,
            form_id=form_id,
            channel_id=channel_id,
            author_id=author_id,
            status_id=status_id,
            number=number,
            is_closed=False,
        )
        session.add(ticket)
        await session.flush()
        return ticket

    @staticmethod
    async def save_responses(
        session: AsyncSession,
        ticket: Ticket,
        responses: list[dict],
    ) -> None:
        for resp in responses:
            r = TicketResponse(
                ticket_id=ticket.id,
                field_id=resp.get("field_id"),
                field_label=resp["field_label"],
                value=resp["value"],
            )
            session.add(r)
        await session.flush()

    @staticmethod
    async def get_by_channel(
        session: AsyncSession, channel_id: int
    ) -> Optional[Ticket]:
        result = await session.execute(
            select(Ticket)
            .where(Ticket.channel_id == channel_id)
            .options(
                selectinload(Ticket.responses),
                selectinload(Ticket.status),
                selectinload(Ticket.panel),
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_id(session: AsyncSession, ticket_id: int) -> Optional[Ticket]:
        result = await session.execute(
            select(Ticket)
            .where(Ticket.id == ticket_id)
            .options(
                selectinload(Ticket.responses),
                selectinload(Ticket.status),
                selectinload(Ticket.panel),
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def update_status(
        session: AsyncSession,
        ticket: Ticket,
        new_status: TicketStatus,
    ) -> None:
        ticket.status_id = new_status.id
        ticket.status = new_status
        if new_status.is_closed and not ticket.is_closed:
            ticket.is_closed = True
            ticket.closed_at = datetime.datetime.utcnow()
        elif not new_status.is_closed:
            ticket.is_closed = False
            ticket.closed_at = None
            ticket.closed_by = None
        await session.flush()

    @staticmethod
    async def assign(
        session: AsyncSession,
        ticket: Ticket,
        assignee_id: Optional[int],
    ) -> None:
        ticket.assignee_id = assignee_id
        await session.flush()

    @staticmethod
    async def close(
        session: AsyncSession,
        ticket: Ticket,
        closed_by: int,
        closed_status: Optional[TicketStatus],
    ) -> None:
        ticket.is_closed = True
        ticket.closed_at = datetime.datetime.utcnow()
        ticket.closed_by = closed_by
        if closed_status:
            ticket.status_id = closed_status.id
            ticket.status = closed_status
        await session.flush()

    @staticmethod
    async def reopen(session: AsyncSession, ticket: Ticket, default_status: Optional[TicketStatus]) -> None:
        ticket.is_closed = False
        ticket.closed_at = None
        ticket.closed_by = None
        if default_status:
            ticket.status_id = default_status.id
            ticket.status = default_status
        await session.flush()

    @staticmethod
    async def get_all_panels(session: AsyncSession, guild_id: int) -> list[TicketPanel]:
        result = await session.execute(
            select(TicketPanel)
            .where(TicketPanel.guild_id == guild_id)
            .order_by(TicketPanel.id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_panel_by_id(session: AsyncSession, panel_id: int) -> Optional[TicketPanel]:
        result = await session.execute(
            select(TicketPanel).where(TicketPanel.id == panel_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_panel(
        session: AsyncSession,
        guild_id: int,
        channel_id: int,
        name: str,
        description: Optional[str],
        color: int,
        category_id: Optional[int],
        form_id: Optional[int],
        button_label: str,
        button_emoji: Optional[str],
        created_by: int,
    ) -> TicketPanel:
        panel = TicketPanel(
            guild_id=guild_id,
            channel_id=channel_id,
            name=name,
            description=description,
            color=color,
            category_id=category_id,
            form_id=form_id,
            button_label=button_label,
            button_emoji=button_emoji if button_emoji and button_emoji.strip() else None,
            created_by=created_by,
        )
        session.add(panel)
        await session.flush()
        return panel

    @staticmethod
    async def update_panel(
        session: AsyncSession,
        panel: TicketPanel,
        **kwargs,
    ) -> TicketPanel:
        for key, value in kwargs.items():
            if hasattr(panel, key) and value is not None:
                setattr(panel, key, value)
        await session.flush()
        return panel

    @staticmethod
    async def delete_panel(session: AsyncSession, panel: TicketPanel) -> None:
        await session.delete(panel)
        await session.flush()

    @staticmethod
    async def get_log_settings(
        session: AsyncSession, guild_id: int
    ) -> Optional[LogSettings]:
        result = await session.execute(
            select(LogSettings).where(LogSettings.guild_id == guild_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_or_create_log_settings(
        session: AsyncSession, guild_id: int
    ) -> LogSettings:
        settings = await TicketService.get_log_settings(session, guild_id)
        if not settings:
            settings = LogSettings(guild_id=guild_id)
            session.add(settings)
            await session.flush()
        return settings

    @staticmethod
    async def get_or_create_notification_settings(
        session: AsyncSession, guild_id: int
    ) -> NotificationSettings:
        result = await session.execute(
            select(NotificationSettings).where(NotificationSettings.guild_id == guild_id)
        )
        settings = result.scalar_one_or_none()
        if not settings:
            settings = NotificationSettings(guild_id=guild_id)
            session.add(settings)
            await session.flush()
        return settings

    @staticmethod
    async def list_open(
        session: AsyncSession, guild_id: int, limit: int = 25
    ) -> list[Ticket]:
        result = await session.execute(
            select(Ticket)
            .where(Ticket.guild_id == guild_id, Ticket.is_closed == False)
            .options(selectinload(Ticket.status))
            .order_by(Ticket.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
