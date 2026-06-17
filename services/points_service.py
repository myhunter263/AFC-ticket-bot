from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import UserPoints

logger = logging.getLogger(__name__)


class PointsService:

    @staticmethod
    async def get_or_create(
        session: AsyncSession, guild_id: int, user_id: int
    ) -> UserPoints:
        result = await session.execute(
            select(UserPoints).where(
                UserPoints.guild_id == guild_id,
                UserPoints.user_id == user_id,
            )
        )
        entry = result.scalar_one_or_none()
        if not entry:
            entry = UserPoints(guild_id=guild_id, user_id=user_id, points=0, total_earned=0)
            session.add(entry)
            await session.flush()
        return entry

    @staticmethod
    async def get_points(session: AsyncSession, guild_id: int, user_id: int) -> int:
        entry = await PointsService.get_or_create(session, guild_id, user_id)
        return entry.points

    @staticmethod
    async def award(
        session: AsyncSession, guild_id: int, user_id: int, amount: int
    ) -> UserPoints:
        entry = await PointsService.get_or_create(session, guild_id, user_id)
        entry.points += amount
        if amount > 0:
            entry.total_earned += amount
        await session.flush()
        return entry

    @staticmethod
    async def set_points(
        session: AsyncSession, guild_id: int, user_id: int, amount: int
    ) -> UserPoints:
        entry = await PointsService.get_or_create(session, guild_id, user_id)
        if amount > entry.points:
            entry.total_earned += amount - entry.points
        entry.points = amount
        await session.flush()
        return entry

    @staticmethod
    async def get_leaderboard(
        session: AsyncSession, guild_id: int, limit: int = 10
    ) -> list[UserPoints]:
        result = await session.execute(
            select(UserPoints)
            .where(UserPoints.guild_id == guild_id, UserPoints.points > 0)
            .order_by(UserPoints.points.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
