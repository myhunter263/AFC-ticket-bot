import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from backend.events import emit
from config import config
from database.models import Guild, FoxholeSyncState
from services.item_catalog_service import ItemCatalogService
from services.item_sync_service import ItemSyncService

logger = logging.getLogger(__name__)


async def sync_once(sessions):
    async with sessions() as session:
        if not await session.scalar(text("SELECT pg_try_advisory_xact_lock(7410091)")):
            return
        guild_ids = list((await session.scalars(select(Guild.id))).all())
        if not guild_ids:
            return
        state = await session.get(FoxholeSyncState, "foxholehq")
        due = not state or not state.last_success_at or datetime.now(timezone.utc).replace(tzinfo=None) - state.last_success_at >= timedelta(hours=max(1, config.FOXHOLEHQ_SYNC_INTERVAL_HOURS))
        if due:
            result = await ItemSyncService.sync(session, guild_ids[0])
            for guild_id in guild_ids:
                await emit(session, guild_id, "foxholehq.cache_updated", {"success": result.success})
        for guild_id in guild_ids:
            await ItemSyncService.ensure_localizations(session, guild_id)
            await ItemCatalogService.ensure_seed(session, guild_id)
        await session.commit()


async def run(sessions):
    while True:
        try:
            await sync_once(sessions)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Catalog refresh failed: %s", type(exc).__name__)
        await asyncio.sleep(3600)
