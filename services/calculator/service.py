from __future__ import annotations

import logging
from dataclasses import replace

from database.models import FoxholeRecipeOverride
from services.calculator.factory import FactoryCalculator
from services.calculator.models import ItemCalculation, RecipeInput
from services.calculator.mpf import MPFCalculator
from services.foxhole_types import CatalogItem

logger = logging.getLogger(__name__)


class CalculatorService:
    @staticmethod
    def calculation_unit(item: CatalogItem) -> str:
        explicit = item.metadata.get("calculation_unit")
        wiki = item.metadata.get("foxholewiki") or {}
        return str(explicit or wiki.get("calculation_unit") or ("item" if item.is_equipment else "crate"))

    @staticmethod
    def recipes(
        item: CatalogItem,
        overrides: list[FoxholeRecipeOverride] | None = None,
    ) -> list[RecipeInput]:
        recipes = {
            key: RecipeInput(
                key=key,
                building=str(data.get("building") or data.get("method") or key),
                kind=str(data.get("recipe_kind") or ("mpf" if key == "mpf" else "standard")),
                output_quantity=max(1, int(data.get("output_quantity") or 1)),
                output_unit=str(data.get("output_unit") or "item"),
                materials=dict(data.get("materials") or {}),
                source=str(data.get("source") or item.source),
                source_version=data.get("source_version") or item.source_version,
                raw_data=dict(data.get("raw_data") or {}),
            )
            for key, data in item.recipe_details.items()
            if data.get("materials")
        }
        # Keep existing per-guild item settings effective in the shared engine.
        for key, recipe in list(recipes.items()):
            if key == "mpf" or recipe.kind == "mpf":
                if item.overrides.get("mpf_available") is False:
                    recipes.pop(key)
                elif "mpf_base_cost" in item.overrides:
                    recipes[key] = replace(recipe, materials=dict(item.overrides["mpf_base_cost"]), source="manual_override")
            elif "factory_cost" in item.overrides and (
                key == "factory" or recipe.building.casefold() == (item.factory_site or "Factory").casefold()
            ):
                recipes[key] = replace(recipe, materials=dict(item.overrides["factory_cost"]), source="manual_override")
        for row in overrides or []:
            if not row.enabled:
                recipes.pop(row.production_method, None)
                continue
            logger.info(
                "Calculator manual override applied: item=%s method=%s guild=%s",
                item.api_id,
                row.production_method,
                getattr(row, "guild_id", "unknown"),
            )
            recipes[row.production_method] = RecipeInput(
                key=row.production_method,
                building=row.building or row.production_method,
                kind="override",
                output_quantity=max(1, row.output_quantity),
                output_unit=row.output_unit,
                materials=dict(row.materials or {}),
                source="manual_override",
            )
        return list(recipes.values())

    @classmethod
    def calculate(
        cls,
        item: CatalogItem,
        amount: int,
        overrides: list[FoxholeRecipeOverride] | None = None,
        *,
        unit: str | None = None,
    ) -> ItemCalculation:
        if amount < 1 or amount > 100_000:
            raise ValueError("Количество должно быть от 1 до 100000.")
        unit = unit or cls.calculation_unit(item)
        if unit not in {"item", "crate"}:
            raise ValueError("Единица должна быть item или crate.")
        methods = []
        recipe_rows = cls.recipes(item, overrides)
        for recipe in recipe_rows:
            if recipe.kind == "mpf" or recipe.key == "mpf":
                calculated = MPFCalculator.calculate(
                    recipe,
                    amount=amount,
                    calculation_unit=unit,
                    crate_size=item.crate_size,
                    vehicles_per_crate=(
                        item.vehicle_crate_size if item.is_equipment else item.crate_size
                    ),
                    max_crates=item.mpf_max_crates,
                )
                calculated.reference_costs = {
                    size: MPFCalculator.queue_cost(recipe.materials, size)
                    for size in sorted({MPFCalculator.MIN_CRATES, item.mpf_max_crates})
                }
                methods.append(calculated)
            else:
                units_per_crate = (
                    item.vehicle_crate_size if item.is_equipment else item.crate_size
                )
                methods.append(FactoryCalculator.calculate(
                    recipe,
                    amount=amount,
                    calculation_unit=unit,
                    crate_size=item.crate_size,
                    units_per_crate=units_per_crate,
                ))
        represented = {row.building.casefold() for row in methods}
        upstream_methods = list(item.metadata.get("production_methods") or [])
        unavailable = [
            name for name in upstream_methods
            if name.casefold() not in represented
            and not ("mass production" in name.casefold() and any(row.kind == "mpf" for row in methods))
        ]
        if unavailable:
            logger.warning(
                "Calculator methods without recipe cost: item=%s methods=%s",
                item.api_id,
                unavailable,
            )
        return ItemCalculation(
            item_id=item.id,
            name=item.ru_name,
            api_name=item.api_name,
            requested_amount=amount,
            requested_unit=unit,
            crate_size=item.crate_size,
            image_url=item.image_url,
            methods=methods,
            unavailable_methods=unavailable,
        )
