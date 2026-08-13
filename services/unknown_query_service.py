from __future__ import annotations

import datetime

from sqlalchemy import select

from database.models import UnknownItemQuery
from services.text_normalizer import TextNormalizer


class UnknownQueryService:
    @staticmethod
    async def record(session, guild_id: int, raw_query: str) -> None:
        normalized = TextNormalizer.normalize(raw_query)
        if not normalized:
            return
        row = (await session.execute(
            select(UnknownItemQuery).where(
                UnknownItemQuery.guild_id == guild_id,
                UnknownItemQuery.normalized_query == normalized,
            )
        )).scalar_one_or_none()
        now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        if row is None:
            session.add(UnknownItemQuery(
                guild_id=guild_id,
                raw_query=raw_query[:300],
                normalized_query=normalized[:300],
                count=1,
                last_seen_at=now,
            ))
        else:
            row.raw_query = raw_query[:300]
            row.count += 1
            row.last_seen_at = now
        await session.flush()

    @staticmethod
    async def top(session, guild_id: int, limit: int = 25) -> list[UnknownItemQuery]:
        return list((await session.execute(
            select(UnknownItemQuery)
            .where(UnknownItemQuery.guild_id == guild_id)
            .order_by(UnknownItemQuery.count.desc(), UnknownItemQuery.last_seen_at.desc())
            .limit(limit)
        )).scalars().all())
