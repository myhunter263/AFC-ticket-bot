from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    FoxholeItem,
    FoxholeItemAlias,
    FoxholeItemLocalization,
    FoxholeResource,
    FoxholeSeedState,
)
from services.foxhole_api import FoxholeAPIClient
from services.foxhole_transliteration import automatic_transliterations
from services.foxhole_types import CatalogItem
from services.item_sync_service import ItemSyncResult, ItemSyncService
from services.text_normalizer import TextNormalizer

logger = logging.getLogger(__name__)


_LEGACY_SEED_ITEMS = (
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
        "api_id": "foxholehq:falchion",
        "api_name": '85K-b "Falchion"',
        "ru_name": "Фальшион",
        "aliases": [
            "фальшион", "фальшионы", "фальшиона", "фальшионов", "фальш",
            "фальши", "фальшев", "falchion",
        ],
        "category": "vehicles",
        "is_vehicle": True,
        "crate_size": 3,
        "vehicle_crate_size": 3,
        "factory_site": "Garage",
        "factory_cost": {"rmat": 135},
        "mpf_available": True,
        "mpf_max_crates": 5,
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


def _load_seed_items() -> tuple[dict[str, Any], ...]:
    path = Path(__file__).with_name("foxhole_ru_aliases.json")
    try:
        return tuple(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as exc:
        logger.error("Cannot load Foxhole Russian alias seed: %s", exc)
        return _LEGACY_SEED_ITEMS


SEED_ITEMS = _load_seed_items()


class ItemCatalogService:
    SEED_VERSION = 4

    @staticmethod
    async def _upsert_seed_aliases(
        session: AsyncSession,
        localization: FoxholeItemLocalization,
        aliases: list[str],
        alias_type: str,
        priority: int,
    ) -> None:
        existing_result = await session.execute(
            select(FoxholeItemAlias).where(
                FoxholeItemAlias.localization_id == localization.id
            )
        )
        existing = {
            alias.normalized_alias: alias for alias in existing_result.scalars().all()
        }
        # The session deliberately has autoflush disabled. Include aliases queued
        # by an earlier seed layer so manual aliases can replace their metadata
        # without scheduling a duplicate INSERT in the same transaction.
        existing.update({
            alias.normalized_alias: alias
            for alias in session.new
            if isinstance(alias, FoxholeItemAlias)
            and alias.localization_id == localization.id
        })
        for alias in aliases:
            normalized = TextNormalizer.normalize(alias)
            if not normalized:
                continue
            if normalized not in existing:
                row = FoxholeItemAlias(
                    localization_id=localization.id,
                    alias=alias,
                    normalized_alias=normalized,
                    alias_type=alias_type,
                    priority=priority,
                )
                session.add(row)
                existing[normalized] = row
            elif existing[normalized].created_by is None:
                existing[normalized].alias_type = alias_type
                existing[normalized].priority = priority
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
        production_group = str(raw.get("production_group") or "").casefold()
        if production_group not in {"item", "equipment"}:
            production_group = "equipment" if (
                is_vehicle or category_text in {"vehicles", "structures"}
            ) else "item"
        return {
            "api_id": str(api_id),
            "api_name": str(api_name),
            "category": str(category) if category else None,
            "is_vehicle": is_vehicle,
            "production_group": production_group,
            "crate_size": int(raw.get("numberProduced") or raw.get("amountProduced") or raw.get("crate_size") or 1),
            "vehicle_crate_size": int(raw.get("vehicle_crate_size") or 3),
            "factory_site": raw.get("factory_site") or ("Garage" if is_vehicle else "Factory"),
            "factory_cost": ItemCatalogService._cost(raw),
            "mpf_available": bool(raw.get("isMpfCraftable") or raw.get("isMfpCraftable") or raw.get("mpf_available")),
            "mpf_max_crates": int(raw.get("mpf_max_crates") or (5 if production_group == "equipment" else 9)),
            "raw_data": raw,
        }

    @staticmethod
    async def ensure_seed(session: AsyncSession, guild_id: int) -> None:
        seed_state = await session.get(FoxholeSeedState, guild_id)
        if seed_state and seed_state.seed_version >= ItemCatalogService.SEED_VERSION:
            return
        all_items = list((await session.execute(select(FoxholeItem))).scalars().all())
        localization_by_item_id = {
            row.item_id: row for row in (await session.execute(
                select(FoxholeItemLocalization).where(
                    FoxholeItemLocalization.guild_id == guild_id
                )
            )).scalars().all()
        }
        for item in all_items:
            if not item.is_active:
                continue
            localization = localization_by_item_id.get(item.id)
            if localization is None:
                localization = FoxholeItemLocalization(
                    guild_id=guild_id,
                    item_id=item.id,
                    ru_name=None,
                    translation_status="missing",
                )
                session.add(localization)
                await session.flush()
                localization_by_item_id[item.id] = localization
            generated = automatic_transliterations(item.api_name)
            if (
                generated
                and (not localization.ru_name or localization.translation_status == "missing")
            ):
                localization.ru_name = generated[-1].capitalize()
                localization.translation_status = "auto_transliterated"
            await ItemCatalogService._upsert_seed_aliases(
                session, localization, generated, "auto_transliteration", 70
            )
        missing_items: list[str] = []
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
                logger.warning("Foxhole alias seed item not found: %s", data["api_id"])
                missing_items.append(data["api_id"])
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
            elif (
                not localization.ru_name
                or localization.translation_status in {"missing", "auto_transliterated"}
            ):
                localization.ru_name = data["ru_name"]
                localization.translation_status = "translated"
            await ItemCatalogService._upsert_seed_aliases(
                session,
                localization,
                data["aliases"],
                data.get("alias_type", "seed"),
                int(data.get("priority", 100)),
            )
        if missing_items:
            logger.warning(
                "Foxhole alias seed postponed; %d catalog items are not imported yet",
                len(missing_items),
            )
            await session.flush()
            return
        if seed_state is None:
            seed_state = FoxholeSeedState(guild_id=guild_id)
            session.add(seed_state)
        seed_state.seed_version = ItemCatalogService.SEED_VERSION
        await session.flush()

    @staticmethod
    async def dictionary_status(session: AsyncSession, guild_id: int) -> dict[str, int]:
        rows = list((await session.execute(
            select(FoxholeItemLocalization)
            .join(FoxholeItem)
            .where(
                FoxholeItemLocalization.guild_id == guild_id,
                FoxholeItem.is_active == True,
            )
            .options(selectinload(FoxholeItemLocalization.aliases))
        )).scalars().all())
        return {
            "total": len(rows),
            "translated": sum(
                bool(row.ru_name) and row.translation_status != "missing" for row in rows
            ),
            "with_aliases": sum(bool(row.aliases) for row in rows),
            "without_dictionary": sum(not row.ru_name and not row.aliases for row in rows),
        }

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
        resource_sizes = dict((await session.execute(
            select(FoxholeResource.resource_key, FoxholeResource.crate_size)
        )).all())
        catalog: list[CatalogItem] = []
        for localization in result.scalars().all():
            item = localization.item
            overrides = localization.overrides or {}
            recipes = {recipe.production_method: recipe for recipe in item.production_recipes}
            production_group = (
                localization.production_group_override
                or overrides.get("production_group")
                or item.production_group
            )
            default_mpf_max = 5 if production_group == "equipment" else 9
            mpf_max_crates = int(overrides.get(
                "mpf_max_crates",
                item.mpf_max_crates or default_mpf_max,
            ))
            if localization.production_group_override and "mpf_max_crates" not in overrides:
                mpf_max_crates = default_mpf_max
            catalog.append(CatalogItem(
                id=item.id,
                api_id=item.api_id,
                api_name=item.api_name,
                ru_name=localization.ru_name or item.api_name,
                aliases=[alias.alias for alias in localization.aliases],
                alias_metadata={
                    alias.normalized_alias: {
                        "alias_type": alias.alias_type,
                        "priority": alias.priority,
                    }
                    for alias in localization.aliases
                },
                category=overrides.get("category", item.category),
                is_vehicle=(
                    localization.is_vehicle_override
                    if localization.is_vehicle_override is not None
                    else item.is_vehicle
                ),
                production_group=production_group,
                crate_size=int(overrides.get("crate_size", item.crate_size)),
                vehicle_crate_size=int(overrides.get("vehicle_crate_size", item.vehicle_crate_size)),
                factory_site=overrides.get("factory_site", item.factory_site),
                factory_cost=overrides.get("factory_cost", item.factory_cost or {}),
                mpf_base_cost=overrides.get(
                    "mpf_base_cost",
                    (recipes.get("mpf").materials if recipes.get("mpf") else {}),
                ),
                mpf_available=bool(overrides.get("mpf_available", item.mpf_available)),
                mpf_max_crates=mpf_max_crates,
                source=item.source,
                source_version=item.source_version,
                synced_at=item.synced_at,
                overrides=overrides,
                resource_crate_sizes=resource_sizes,
                recipe_details={
                    method: {
                        "method": recipe.production_method,
                        "output_quantity": recipe.output_quantity,
                        "output_unit": recipe.output_unit,
                        "materials": recipe.materials or {},
                        "raw_data": recipe.raw_data or {},
                    }
                    for method, recipe in recipes.items()
                },
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
    async def add_alias(
        session: AsyncSession,
        localization: FoxholeItemLocalization,
        alias: str,
        created_by: int,
        alias_type: str = "custom",
        priority: int = 100,
    ) -> FoxholeItemAlias:
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
            alias_type=alias_type[:30],
            priority=max(0, min(200, priority)),
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
    async def export_dictionary(session: AsyncSession, guild_id: int) -> list[dict[str, Any]]:
        rows = list((await session.execute(
            select(FoxholeItemLocalization)
            .join(FoxholeItemLocalization.item)
            .where(FoxholeItemLocalization.guild_id == guild_id)
            .options(
                selectinload(FoxholeItemLocalization.item),
                selectinload(FoxholeItemLocalization.aliases),
            )
            .order_by(FoxholeItem.api_name)
        )).scalars().all())
        return [
            {
                "api_id": row.item.api_id,
                "api_name": row.item.api_name,
                "ru_name": row.ru_name,
                "aliases": [
                    {
                        "alias": alias.alias,
                        "alias_type": alias.alias_type,
                        "priority": alias.priority,
                    }
                    for alias in row.aliases
                ],
            }
            for row in rows
        ]

    @staticmethod
    async def import_dictionary(
        session: AsyncSession,
        guild_id: int,
        entries: list[dict[str, Any]],
        created_by: int,
    ) -> dict[str, int]:
        items = {
            item.api_id: item for item in (await session.execute(
                select(FoxholeItem).where(FoxholeItem.is_active == True)
            )).scalars().all()
        }
        added = updated = skipped = 0
        for entry in entries:
            item = items.get(str(entry.get("api_id") or ""))
            if item is None:
                skipped += 1
                continue
            localization = await ItemCatalogService.get_localization(
                session, guild_id, item.id
            )
            if localization is None:
                localization = FoxholeItemLocalization(
                    guild_id=guild_id,
                    item_id=item.id,
                    translation_status="missing",
                )
                session.add(localization)
                await session.flush()
            ru_name = str(entry.get("ru_name") or "").strip()
            if ru_name and ru_name != localization.ru_name:
                localization.ru_name = ru_name[:200]
                localization.translation_status = "translated"
                updated += 1
            existing = {alias.normalized_alias: alias for alias in localization.aliases}
            for alias_data in entry.get("aliases") or []:
                if isinstance(alias_data, str):
                    alias_text = alias_data
                    alias_type = "custom"
                    priority = 100
                elif isinstance(alias_data, dict):
                    alias_text = str(alias_data.get("alias") or "")
                    alias_type = str(alias_data.get("alias_type") or "custom")
                    try:
                        priority = int(alias_data.get("priority", 100))
                    except (TypeError, ValueError):
                        priority = 100
                else:
                    continue
                normalized = TextNormalizer.normalize(alias_text)
                if not normalized:
                    continue
                current = existing.get(normalized)
                if current is None:
                    current = FoxholeItemAlias(
                        localization_id=localization.id,
                        alias=alias_text.strip()[:200],
                        normalized_alias=normalized[:200],
                        alias_type=alias_type[:30],
                        priority=max(0, min(200, priority)),
                        created_by=created_by,
                    )
                    session.add(current)
                    existing[normalized] = current
                    added += 1
                else:
                    current.alias_type = alias_type[:30]
                    current.priority = max(0, min(200, priority))
        await session.flush()
        return {"added": added, "updated": updated, "skipped": skipped}

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
        production_group = values.get("production_group")
        if production_group is not None:
            normalized_group = str(production_group).strip().casefold()
            if normalized_group not in {"auto", "item", "equipment"}:
                raise ValueError("production_group должен быть AUTO, ITEM или EQUIPMENT")
            localization.production_group_override = (
                None if normalized_group == "auto" else normalized_group
            )
            overrides.pop("production_group", None)
            localization.overrides = overrides or None
        await session.flush()
