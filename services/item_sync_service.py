from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    FoxholeItem,
    FoxholeItemLocalization,
    FoxholeProductionRecipe,
    FoxholeSyncState,
)
from services.foxhole_api import FoxholeDataError, FoxholeDataProvider, FoxholeHQDataProvider
from services.text_normalizer import TextNormalizer

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ItemSyncResult:
    success: bool
    changed: bool = False
    item_count: int = 0
    recipe_count: int = 0
    created: int = 0
    updated: int = 0
    renamed: int = 0
    deactivated: int = 0
    untranslated: int = 0
    source_version: str | None = None
    dataset_hash: str | None = None
    error: str | None = None


class ItemSyncService:
    SOURCE = "foxholehq"

    @classmethod
    async def sync(
        cls,
        session: AsyncSession,
        guild_id: int,
        provider: FoxholeDataProvider | None = None,
    ) -> ItemSyncResult:
        now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        state = await cls._state(session)
        state.last_attempt_at = now
        try:
            dataset = await (provider or FoxholeHQDataProvider()).fetch_dataset()
        except FoxholeDataError as exc:
            state.last_error = str(exc)[:4000]
            await session.flush()
            logger.warning("FoxholeHQ sync rejected: %s", exc)
            return ItemSyncResult(success=False, error=str(exc))

        if state.dataset_hash == dataset.dataset_hash:
            state.last_success_at = now
            state.last_error = None
            await cls._ensure_localizations(session, guild_id)
            untranslated = await cls._untranslated_count(session, guild_id)
            await session.flush()
            return ItemSyncResult(
                success=True,
                changed=False,
                item_count=state.item_count,
                recipe_count=state.recipe_count,
                untranslated=untranslated,
                source_version=state.source_version,
                dataset_hash=state.dataset_hash,
            )

        existing = list((await session.execute(
            select(FoxholeItem).options(selectinload(FoxholeItem.production_recipes))
        )).scalars().all())
        by_id = {item.api_id: item for item in existing}
        by_name = {
            TextNormalizer.normalize(item.api_name, remove_service_words=False): item
            for item in existing
        }
        fingerprints: dict[str, list[FoxholeItem]] = {}
        for item in existing:
            if item.upstream_fingerprint:
                fingerprints.setdefault(item.upstream_fingerprint, []).append(item)

        seen: set[int] = set()
        created = updated = renamed = 0
        item_by_api_id: dict[str, FoxholeItem] = {}
        for data in dataset.items:
            item = by_id.get(data["api_id"])
            if item is None:
                name_key = TextNormalizer.normalize(data["api_name"], remove_service_words=False)
                item = by_name.get(name_key)
            if item is None:
                candidates = fingerprints.get(data["upstream_fingerprint"], [])
                if len(candidates) == 1 and candidates[0].id not in seen:
                    item = candidates[0]
                    renamed += 1
                    logger.warning("FoxholeHQ rename detected: %s -> %s", item.api_name, data["api_name"])
            if item is None:
                item = FoxholeItem(api_id=data["api_id"], api_name=data["api_name"])
                session.add(item)
                created += 1
            else:
                updated += 1

            source_updated_at = (
                datetime.datetime.fromisoformat(data["source_updated_at"])
                if data.get("source_updated_at") else None
            )
            for field in (
                "api_id", "api_name", "category", "faction", "is_vehicle", "crate_size",
                "amount_produced", "vehicle_crate_size", "factory_site", "factory_cost",
                "mpf_available", "mpf_max_crates", "source", "source_version",
                "upstream_fingerprint", "raw_data",
            ):
                setattr(item, field, data[field])
            item.source_updated_at = source_updated_at
            item.dataset_hash = dataset.dataset_hash
            item.synced_at = now
            item.is_active = True
            await session.flush()
            seen.add(item.id)
            item_by_api_id[data["api_id"]] = item

        deactivated = 0
        for item in existing:
            if item.source == cls.SOURCE and item.id not in seen and item.is_active:
                item.is_active = False
                deactivated += 1

        synced_item_ids = [item.id for item in item_by_api_id.values()]
        if synced_item_ids:
            await session.execute(
                delete(FoxholeProductionRecipe).where(
                    FoxholeProductionRecipe.item_id.in_(synced_item_ids)
                )
            )
            await session.flush()
        for recipe in dataset.recipes:
            item = item_by_api_id[recipe["api_id"]]
            session.add(FoxholeProductionRecipe(
                item_id=item.id,
                production_method=recipe["production_method"],
                output_quantity=recipe["output_quantity"],
                output_unit=recipe["output_unit"],
                materials=recipe["materials"],
                raw_data=recipe.get("raw_data"),
            ))

        await cls._ensure_localizations(session, guild_id)
        untranslated = await cls._untranslated_count(session, guild_id)
        state.source_version = dataset.source_version
        state.source_updated_at = dataset.source_updated_at
        state.dataset_hash = dataset.dataset_hash
        state.last_success_at = now
        state.last_error = None
        state.item_count = len(dataset.items)
        state.recipe_count = len(dataset.recipes)
        await session.flush()
        logger.info(
            "FoxholeHQ sync applied: items=%d recipes=%d created=%d renamed=%d deactivated=%d",
            len(dataset.items), len(dataset.recipes), created, renamed, deactivated,
        )
        return ItemSyncResult(
            success=True,
            changed=True,
            item_count=len(dataset.items),
            recipe_count=len(dataset.recipes),
            created=created,
            updated=updated,
            renamed=renamed,
            deactivated=deactivated,
            untranslated=untranslated,
            source_version=dataset.source_version,
            dataset_hash=dataset.dataset_hash,
        )

    @classmethod
    async def status(cls, session: AsyncSession, guild_id: int) -> dict:
        state = await cls._state(session)
        return {
            "source": cls.SOURCE,
            "source_version": state.source_version,
            "source_updated_at": state.source_updated_at,
            "dataset_hash": state.dataset_hash,
            "last_attempt_at": state.last_attempt_at,
            "last_success_at": state.last_success_at,
            "last_error": state.last_error,
            "item_count": state.item_count,
            "recipe_count": state.recipe_count,
            "untranslated": await cls._untranslated_count(session, guild_id),
        }

    @classmethod
    async def ensure_localizations(cls, session: AsyncSession, guild_id: int) -> None:
        await cls._ensure_localizations(session, guild_id)

    @classmethod
    async def _state(cls, session: AsyncSession) -> FoxholeSyncState:
        state = await session.get(FoxholeSyncState, cls.SOURCE)
        if state is None:
            state = FoxholeSyncState(source=cls.SOURCE)
            session.add(state)
            await session.flush()
        return state

    @staticmethod
    async def _ensure_localizations(session: AsyncSession, guild_id: int) -> None:
        items = list((await session.execute(
            select(FoxholeItem).where(FoxholeItem.is_active == True)
        )).scalars().all())
        localized_ids = set((await session.execute(
            select(FoxholeItemLocalization.item_id).where(
                FoxholeItemLocalization.guild_id == guild_id
            )
        )).scalars().all())
        for item in items:
            if item.id not in localized_ids:
                session.add(FoxholeItemLocalization(
                    guild_id=guild_id,
                    item_id=item.id,
                    ru_name=None,
                    translation_status="missing",
                ))
        await session.flush()

    @staticmethod
    async def _untranslated_count(session: AsyncSession, guild_id: int) -> int:
        rows = (await session.execute(
            select(FoxholeItemLocalization).join(FoxholeItem).where(
                FoxholeItemLocalization.guild_id == guild_id,
                FoxholeItem.is_active == True,
                FoxholeItemLocalization.translation_status == "missing",
            )
        )).scalars().all()
        return len(rows)
