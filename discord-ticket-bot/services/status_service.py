from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import TicketStatus


class StatusService:

    @staticmethod
    async def get_all(session: AsyncSession, guild_id: int) -> list[TicketStatus]:
        result = await session.execute(
            select(TicketStatus)
            .where(TicketStatus.guild_id == guild_id)
            .order_by(TicketStatus.order)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(session: AsyncSession, status_id: int) -> Optional[TicketStatus]:
        result = await session.execute(
            select(TicketStatus).where(TicketStatus.id == status_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_default(session: AsyncSession, guild_id: int) -> Optional[TicketStatus]:
        result = await session.execute(
            select(TicketStatus).where(
                TicketStatus.guild_id == guild_id,
                TicketStatus.is_default == True,
            )
        )
        status = result.scalar_one_or_none()
        if status:
            return status
        result = await session.execute(
            select(TicketStatus)
            .where(TicketStatus.guild_id == guild_id)
            .order_by(TicketStatus.order)
            .limit(1)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        session: AsyncSession,
        guild_id: int,
        name: str,
        color: int,
        emoji: Optional[str] = None,
        is_default: bool = False,
        is_closed: bool = False,
    ) -> TicketStatus:
        if is_default:
            result = await session.execute(
                select(TicketStatus).where(
                    TicketStatus.guild_id == guild_id,
                    TicketStatus.is_default == True,
                )
            )
            for existing in result.scalars().all():
                existing.is_default = False

        result = await session.execute(
            select(TicketStatus)
            .where(TicketStatus.guild_id == guild_id)
            .order_by(TicketStatus.order.desc())
            .limit(1)
        )
        last = result.scalar_one_or_none()
        next_order = (last.order + 1) if last else 0

        status = TicketStatus(
            guild_id=guild_id,
            name=name,
            color=color,
            emoji=emoji,
            order=next_order,
            is_default=is_default,
            is_closed=is_closed,
        )
        session.add(status)
        await session.flush()
        return status

    @staticmethod
    async def update(
        session: AsyncSession,
        status: TicketStatus,
        name: Optional[str] = None,
        color: Optional[int] = None,
        emoji: Optional[str] = None,
        is_default: Optional[bool] = None,
        is_closed: Optional[bool] = None,
    ) -> TicketStatus:
        if name is not None:
            status.name = name
        if color is not None:
            status.color = color
        if emoji is not None:
            status.emoji = emoji if emoji.strip() else None
        if is_default is not None:
            if is_default:
                result = await session.execute(
                    select(TicketStatus).where(
                        TicketStatus.guild_id == status.guild_id,
                        TicketStatus.is_default == True,
                        TicketStatus.id != status.id,
                    )
                )
                for existing in result.scalars().all():
                    existing.is_default = False
            status.is_default = is_default
        if is_closed is not None:
            status.is_closed = is_closed
        await session.flush()
        return status

    @staticmethod
    async def delete(session: AsyncSession, status: TicketStatus) -> None:
        await session.delete(status)
        await session.flush()

    @staticmethod
    async def ensure_defaults(session: AsyncSession, guild_id: int) -> None:
        result = await session.execute(
            select(TicketStatus).where(TicketStatus.guild_id == guild_id)
        )
        existing = result.scalars().all()
        if existing:
            return

        defaults = [
            TicketStatus(guild_id=guild_id, name="Новая", color=0x5865F2, emoji="🆕", order=0, is_default=True, is_closed=False),
            TicketStatus(guild_id=guild_id, name="В работе", color=0xFEE75C, emoji="⚙️", order=1, is_default=False, is_closed=False),
            TicketStatus(guild_id=guild_id, name="Ожидание клиента", color=0xEB459E, emoji="⏳", order=2, is_default=False, is_closed=False),
            TicketStatus(guild_id=guild_id, name="Завершена", color=0x57F287, emoji="✅", order=3, is_default=False, is_closed=True),
            TicketStatus(guild_id=guild_id, name="Отменена", color=0xED4245, emoji="❌", order=4, is_default=False, is_closed=True),
        ]
        session.add_all(defaults)
        await session.flush()
