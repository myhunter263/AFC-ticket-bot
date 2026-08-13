from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    FoxholeItem,
    FoxholeItemAlias,
    FoxholeItemLocalization,
)
from services.foxhole_api import FoxholeAPIClient
from services.foxhole_types import CatalogItem
from services.item_sync_service import ItemSyncResult, ItemSyncService
from services.text_normalizer import TextNormalizer

logger = logging.getLogger(__name__)


SEED_ITEMS = (
    {
        "api_id": "argenti-r-ii",
        "api_name": "Argenti r.II Rifle",
        "ru_name": "Аргенти",
        "aliases": ["аргенти", "аргентя", "аргенти винтовка", "арг", "argenti"],
        "category": "small_arms",
        "is_vehicle": False,
        "crate_size": 20,
        "factory_site": "Factory",
        "factory_cost": {"bmat": 100},
        "mpf_available": True,
        "mpf_max_crates": 9,
    },
    {
        "api_id": "7-62mm",
        "api_name": "7.62mm",
        "ru_name": "Патроны 7.62 мм",
        "aliases": [
            "7.62", "762", "7 62", "7.62мм", "762мм", "патроны 762",
            "патрики 762", "патроны 7.62",
        ],
        "category": "small_arms",
        "is_vehicle": False,
        "crate_size": 40,
        "factory_site": "Factory",
        "factory_cost": {"bmat": 80},
        "mpf_available": True,
        "mpf_max_crates": 9,
    },
    {
        "api_id": "86k-a-bardiche",
        "api_name": '86K-a "Bardiche"',
        "ru_name": "Бардиш",
        "aliases": ["бардиш", "бардич", "бердыш", "берды", "бард", "bardiche"],
        "category": "vehicle",
        "is_vehicle": True,
        "crate_size": 1,
        "vehicle_crate_size": 3,
        "factory_site": "Garage",
        "factory_cost": {"rmat": 165},
        "mpf_available": True,
        "mpf_max_crates": 5,
    },
)


class ItemCatalogService:
    @staticmethod
    def _cost(raw: dict[str, Any]) -> dict[str, int]:
        source = raw.get("cost") or raw.get("factory_cost") or raw.get("factoryCost") or {}
        if not isinstance(source, dict):
            return {}
        aliases = {
            "bmats": "bmat", "basicmaterials": "bmat", "basic_materials": "bmat",
            "rmats": "rmat", "refinedmaterials": "rmat", "refined_materials": "rmat",
            "emats": "emat", "explosivematerials": "emat", "explosive_materials": "emat",
            "hemats": "hemat", "heavyexplosivematerials": "hemat", "heavy_explosive_materials": "hemat",
        }
        result: dict[str, int] = {}
        for key, value in source.items():
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            normalized = str(key).casefold().replace(" ", "").replace("-", "")
            result[aliases.get(normalized, normalized)] = number
        return result

    @staticmethod
    def _mapped_api_item(raw: dict[str, Any]) -> dict[str, Any] | None:
        api_name = raw.get("itemName") or raw.get("name") or raw.get("api_name")
        if not api_name:
            return None
        api_id = raw.get("_id") or raw.get("id") or raw.get("api_id") or TextNormalizer.compact(str(api_name))
        category = raw.get("itemCategory") or raw.get("category")
        category_text = str(category or "").casefold()
        is_vehicle = bool(raw.get("is_vehicle") or raw.get("isVehicle")) or any(
            marker in category_text for marker in ("vehicle", "tank", "truck")
        )
        return {
            "api_id": str(api_id),
            "api_name": str(api_name),
            "category": str(category) if category else None,
            "is_vehicle": is_vehicle,
            "crate_size": int(raw.get("numberProduced") or raw.get("amountProduced") or raw.get("crate_size") or 1),
            "vehicle_crate_size": int(raw.get("vehicle_crate_size") or 3),
            "factory_site": raw.get("factory_site") or ("Garage" if is_vehicle else "Factory"),
            "factory_cost": ItemCatalogService._cost(raw),
            "mpf_available": bool(raw.get("isMpfCraftable") or raw.get("isMfpCraftable") or raw.get("mpf_available")),
            "mpf_max_crates": int(raw.get("mpf_max_crates") or (5 if is_vehicle else 9)),
            "raw_data": raw,
        }

    @staticmethod
    async def ensure_seed(session: AsyncSession, guild_id: int) -> None:
        all_items = list((await session.execute(select(FoxholeItem))).scalars().all())
        for data in SEED_ITEMS:
            wanted_name = TextNormalizer.normalize(data["api_name"], remove_service_words=False)
            item = next(
                (
                    row for row in all_items
                    if row.api_id == data["api_id"] or TextNormalizer.normalize(
                        row.api_name, remove_service_words=False
                    ) == wanted_name
                ),
                None,
            )
            if item is None:
                # Bundled values are localization hints, never an upstream fallback.
                continue
            localization_result = await session.execute(
                select(FoxholeItemLocalization).where(
                    FoxholeItemLocalization.guild_id == guild_id,
                    FoxholeItemLocalization.item_id == item.id,
                )
            )
            localization = localization_result.scalar_one_or_none()
            if localization is None:
                localization = FoxholeItemLocalization(
                    guild_id=guild_id, item_id=item.id, ru_name=data["ru_name"],
                    translation_status="translated",
                )
                session.add(localization)
                await session.flush()
            elif not localization.ru_name or localization.translation_status == "missing":
                localization.ru_name = data["ru_name"]
                localization.translation_status = "translated"
            existing_result = await session.execute(
                select(FoxholeItemAlias.normalized_alias).where(
                    FoxholeItemAlias.localization_id == localization.id
                )
            )
            existing = set(existing_result.scalars().all())
            for alias in data["aliases"]:
                normalized = TextNormalizer.normalize(alias)
                if normalized not in existing:
                    session.add(FoxholeItemAlias(
                        localization_id=localization.id,
                        alias=alias,
                        normalized_alias=normalized,
                    ))
                    existing.add(normalized)
        await session.flush()

    @staticmethod
    async def get_catalog(session: AsyncSession, guild_id: int) -> list[CatalogItem]:
        await ItemCatalogService.ensure_seed(session, guild_id)
        result = await session.execute(
            select(FoxholeItemLocalization)
            .join(FoxholeItem)
            .where(
                FoxholeItemLocalization.guild_id == guild_id,
                FoxholeItem.is_active == True,
            )
            .options(
                selectinload(FoxholeItemLocalization.item),
                selectinload(FoxholeItemLocalization.aliases),
                selectinload(FoxholeItemLocalization.item).selectinload(FoxholeItem.production_recipes),
            )
            .order_by(func.coalesce(FoxholeItemLocalization.ru_name, FoxholeItem.api_name))
        )
        catalog: list[CatalogItem] = []
        for localization in result.scalars().all():
            item = localization.item
            overrides = localization.overrides or {}
            recipes = {recipe.production_method: recipe for recipe in item.production_recipes}
            catalog.append(CatalogItem(
                id=item.id,
                api_id=item.api_id,
                api_name=item.api_name,
                ru_name=localization.ru_name or item.api_name,
                aliases=[alias.alias for alias in localization.aliases],
                category=overrides.get("category", item.category),
                is_vehicle=(
                    localization.is_vehicle_override
                    if localization.is_vehicle_override is not None
                    else item.is_vehicle
                ),
                crate_size=int(overrides.get("crate_size", item.crate_size)),
                vehicle_crate_size=int(overrides.get("vehicle_crate_size", item.vehicle_crate_size)),
                factory_site=overrides.get("factory_site", item.factory_site),
                factory_cost=overrides.get("factory_cost", item.factory_cost or {}),
                mpf_base_cost=overrides.get(
                    "mpf_base_cost",
                    (recipes.get("mpf").materials if recipes.get("mpf") else {}),
                ),
                mpf_available=bool(overrides.get("mpf_available", item.mpf_available)),
                mpf_max_crates=int(overrides.get("mpf_max_crates", item.mpf_max_crates)),
                source=item.source,
                source_version=item.source_version,
                synced_at=item.synced_at,
                overrides=overrides,
            ))
        return catalog

    @staticmethod
    async def sync(
        session: AsyncSession,
        guild_id: int,
        client: FoxholeAPIClient | None = None,
    ) -> ItemSyncResult:
        return await ItemSyncService.sync(session, guild_id, provider=client)

    @staticmethod
    async def search(session: AsyncSession, guild_id: int, query: str, limit: int = 20) -> list[FoxholeItemLocalization]:
        normalized = TextNormalizer.normalize(query)
        result = await session.execute(
            select(FoxholeItemLocalization)
            .join(FoxholeItemLocalization.item)
            .outerjoin(FoxholeItemLocalization.aliases)
            .where(
                FoxholeItemLocalization.guild_id == guild_id,
                or_(
                    func.lower(FoxholeItemLocalization.ru_name).contains(normalized),
                    func.lower(FoxholeItem.api_name).contains(normalized),
                    FoxholeItemAlias.normalized_alias.contains(normalized),
                ),
            )
            .options(
                selectinload(FoxholeItemLocalization.item),
                selectinload(FoxholeItemLocalization.aliases),
            )
            .distinct()
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_localization(session: AsyncSession, guild_id: int, item_id: int) -> FoxholeItemLocalization | None:
        result = await session.execute(
            select(FoxholeItemLocalization)
            .where(
                FoxholeItemLocalization.guild_id == guild_id,
                FoxholeItemLocalization.item_id == item_id,
            )
            .options(
                selectinload(FoxholeItemLocalization.item),
                selectinload(FoxholeItemLocalization.aliases),
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def add_alias(session: AsyncSession, localization: FoxholeItemLocalization, alias: str, created_by: int) -> FoxholeItemAlias:
        normalized = TextNormalizer.normalize(alias)
        if not normalized:
            raise ValueError("Алиас не может быть пустым.")
        exists = await session.execute(
            select(FoxholeItemAlias).where(
                FoxholeItemAlias.localization_id == localization.id,
                FoxholeItemAlias.normalized_alias == normalized,
            )
        )
        if exists.scalar_one_or_none():
            raise ValueError("Такой алиас уже существует у предмета.")
        row = FoxholeItemAlias(
            localization_id=localization.id,
            alias=alias.strip(),
            normalized_alias=normalized,
            created_by=created_by,
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def remove_alias(session: AsyncSession, localization: FoxholeItemLocalization, alias: str) -> bool:
        normalized = TextNormalizer.normalize(alias)
        result = await session.execute(
            select(FoxholeItemAlias).where(
                FoxholeItemAlias.localization_id == localization.id,
                FoxholeItemAlias.normalized_alias == normalized,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return False
        await session.delete(row)
        await session.flush()
        return True

    @staticmethod
    async def update_overrides(
        session: AsyncSession,
        localization: FoxholeItemLocalization,
        **values: Any,
    ) -> None:
        overrides = dict(localization.overrides or {})
        for key, value in values.items():
            if value is not None:
                overrides[key] = value
        localization.overrides = overrides or None
        if values.get("is_vehicle") is not None:
            localization.is_vehicle_override = bool(values["is_vehicle"])
            overrides.pop("is_vehicle", None)
            localization.overrides = overrides or None
        await session.flush()
