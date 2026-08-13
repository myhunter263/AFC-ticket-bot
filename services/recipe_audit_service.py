from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import FoxholeItem, FoxholeItemLocalization, FoxholeResource
from services.cost_calculators import MPFCostCalculator
from services.foxhole_api import FoxholeDataset
from services.foxhole_types import CatalogItem


@dataclass(slots=True)
class RecipeAuditReport:
    item_count: int = 0
    recipe_count: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    garage_anomalies: int = 0
    factory_anomalies: int = 0
    mpf_anomalies: int = 0
    missing_recipes: int = 0
    manual_overrides: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RecipeAuditService:
    KNOWN_RESOURCES = {"bmat", "rmat", "emat", "hemat"}

    @classmethod
    def audit_dataset(cls, dataset: FoxholeDataset) -> RecipeAuditReport:
        report = RecipeAuditReport(len(dataset.items), len(dataset.recipes))
        recipes_by_id: dict[str, list[dict[str, Any]]] = {}
        for recipe in dataset.recipes:
            recipes_by_id.setdefault(recipe["api_id"], []).append(recipe)
            cls._validate_recipe(recipe, report)
        for resource, size in (dataset.resource_crate_sizes or {}).items():
            if resource not in cls.KNOWN_RESOURCES or size <= 0:
                report.errors.append(f"Некорректный ящик ресурса {resource}: {size}")
        for item in dataset.items:
            recipes = recipes_by_id.get(item["api_id"], [])
            standard = [row for row in recipes if row["production_method"] != "mpf"]
            mpf = [row for row in recipes if row["production_method"] == "mpf"]
            if not standard:
                report.missing_recipes += 1
                report.errors.append(f"{item['api_name']}: отсутствует основной рецепт")
            if item["mpf_available"] and not mpf:
                report.mpf_anomalies += 1
                report.errors.append(f"{item['api_name']}: отсутствует MPF-рецепт")
            if item["is_vehicle"] and standard:
                row = standard[0]
                if row["output_quantity"] != 1 or row["output_unit"] != "vehicle":
                    report.garage_anomalies += 1
                    report.errors.append(f"{item['api_name']}: неверная единица Garage")
            if item["is_vehicle"] and mpf:
                row = mpf[0]
                if row["output_quantity"] != 1 or row["output_unit"] != "vehicle_crate":
                    report.mpf_anomalies += 1
                    report.errors.append(f"{item['api_name']}: неверная единица MPF")
                if int((row.get("raw_data") or {}).get("vehicles_per_crate") or 0) <= 0:
                    report.mpf_anomalies += 1
                    report.errors.append(f"{item['api_name']}: не указан размер ящика техники")
        return report

    @classmethod
    def _validate_recipe(cls, recipe: dict[str, Any], report: RecipeAuditReport) -> None:
        method = recipe.get("production_method", "unknown")
        materials = recipe.get("materials") or {}
        if int(recipe.get("output_quantity") or 0) <= 0:
            report.errors.append(f"{recipe.get('api_id')}: output_quantity <= 0")
        if not materials:
            report.errors.append(f"{recipe.get('api_id')}: пустая цена {method}")
        for resource, amount in materials.items():
            if resource not in cls.KNOWN_RESOURCES:
                report.errors.append(f"{recipe.get('api_id')}: неизвестный ресурс {resource}")
            if not isinstance(amount, int) or amount <= 0:
                report.errors.append(f"{recipe.get('api_id')}: неверная цена {resource}={amount}")
        if method == "mpf" and recipe.get("output_unit") not in {"crate", "vehicle_crate"}:
            report.mpf_anomalies += 1

    @classmethod
    async def audit_database(cls, session: AsyncSession, guild_id: int) -> RecipeAuditReport:
        items = list((await session.execute(
            select(FoxholeItem)
            .where(FoxholeItem.is_active == True)
            .options(
                selectinload(FoxholeItem.production_recipes),
                selectinload(FoxholeItem.localizations),
            )
        )).scalars().all())
        resource_sizes = dict((await session.execute(
            select(FoxholeResource.resource_key, FoxholeResource.crate_size)
        )).all())
        dataset = FoxholeDataset(
            items=[{
                "api_id": item.api_id,
                "api_name": item.api_name,
                "is_vehicle": item.is_vehicle,
                "mpf_available": item.mpf_available,
            } for item in items if item.source == "foxholehq"],
            recipes=[{
                "api_id": item.api_id,
                "production_method": recipe.production_method,
                "output_quantity": recipe.output_quantity,
                "output_unit": recipe.output_unit,
                "materials": recipe.materials,
                "raw_data": recipe.raw_data,
            } for item in items if item.source == "foxholehq" for recipe in item.production_recipes],
            categories=[], source_version="database", source_updated_at=None,
            dataset_hash="database", resource_crate_sizes=resource_sizes,
        )
        report = cls.audit_dataset(dataset)
        for item in items:
            localization = next(
                (row for row in item.localizations if row.guild_id == guild_id), None
            )
            if localization and localization.overrides:
                report.manual_overrides.append(
                    f"{localization.ru_name or item.api_name}: {localization.overrides}"
                )
        return report

    @staticmethod
    def item_debug(item: CatalogItem) -> dict[str, Any]:
        mpf_cost, queues = MPFCostCalculator().reference_cost(item)
        return {
            "name": item.ru_name,
            "api_name": item.api_name,
            "api_id": item.api_id,
            "standard": item.recipe_details.get(
                (item.factory_site or "factory").casefold().replace(" ", "_"), {}
            ),
            "mpf": item.recipe_details.get("mpf"),
            "mpf_max_queue_cost": mpf_cost,
            "mpf_queues": queues,
            "source": item.source,
            "source_version": item.source_version,
            "overrides": item.overrides,
            "validation": "OK",
        }

    @classmethod
    def compare_with_existing(
        cls,
        existing_items: list[FoxholeItem],
        dataset: FoxholeDataset,
    ) -> RecipeAuditReport:
        report = RecipeAuditReport(len(dataset.items), len(dataset.recipes))
        incoming_items = {row["api_id"]: row for row in dataset.items}
        incoming_recipes = {
            (row["api_id"], row["production_method"]): row
            for row in dataset.recipes
        }
        for item in existing_items:
            if item.source != "foxholehq" or not item.is_active:
                continue
            incoming = incoming_items.get(item.api_id)
            if incoming is None:
                report.warnings.append(f"{item.api_name}: предмет удалён из dataset")
                continue
            for old_recipe in item.production_recipes:
                new_recipe = incoming_recipes.get((item.api_id, old_recipe.production_method))
                if new_recipe is None:
                    report.errors.append(
                        f"{item.api_name}: исчез рецепт {old_recipe.production_method}"
                    )
                    continue
                old_materials = old_recipe.materials or {}
                new_materials = new_recipe.get("materials") or {}
                for resource, old_amount in old_materials.items():
                    new_amount = new_materials.get(resource)
                    if new_amount is None:
                        report.errors.append(
                            f"{item.api_name}: из {old_recipe.production_method} исчез {resource}"
                        )
                    elif old_amount > 0 and (new_amount >= old_amount * 100 or old_amount >= new_amount * 100):
                        report.errors.append(
                            f"{item.api_name}: подозрительный скачок {resource} "
                            f"{old_amount} -> {new_amount}"
                        )
                    elif old_amount != new_amount:
                        report.warnings.append(
                            f"{item.api_name} {old_recipe.production_method} {resource}: "
                            f"{old_amount} -> {new_amount}"
                        )
        return report
