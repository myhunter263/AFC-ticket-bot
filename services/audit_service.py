from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AuditLog

logger = logging.getLogger(__name__)


class AuditService:

    @staticmethod
    async def log(
        session: AsyncSession,
        guild_id: int,
        user_id: int,
        user_name: str,
        action: str,
        target_type: Optional[str] = None,
        target_id: Optional[int] = None,
        details: Optional[dict] = None,
    ) -> None:
        entry = AuditLog(
            guild_id=guild_id,
            user_id=user_id,
            user_name=user_name,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details,
        )
        session.add(entry)
        await session.flush()
        logger.debug("Audit: guild=%d user=%s action=%s", guild_id, user_name, action)

    @staticmethod
    async def get_recent(
        session: AsyncSession,
        guild_id: int,
        limit: int = 20,
        offset: int = 0,
    ) -> list[AuditLog]:
        result = await session.execute(
            select(AuditLog)
            .where(AuditLog.guild_id == guild_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())
