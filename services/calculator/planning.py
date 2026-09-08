"""Expand uniquely identified intermediate recipes without guessing ambiguous routes."""
from dataclasses import asdict, replace

from services.calculator.production_chain import expand_resources, ProductionChainError
from services.calculator.service import CalculatorService
from services.foxhole_wiki import FoxholeWikiDataProvider


def calculate_plan(item, amount, catalog, overrides=(), *, unit=None, choices=None):
    choices = choices or {}
    own_overrides = [r for r in overrides if r.item_id == item.id]
    result = asdict(CalculatorService.calculate(item, amount, own_overrides, unit=unit))
    by_key = {}
    for row in catalog:
        key = FoxholeWikiDataProvider.resource_key(row.api_name)
        by_key.setdefault(key, []).append(row)
    recipes = {}
    ambiguous = {}
    for key, rows in by_key.items():
        if len(rows) != 1:
            ambiguous[key] = "Несколько предметов соответствуют материалу"
            continue
        row = rows[0]
        options = CalculatorService.recipes(row, [r for r in overrides if r.item_id == row.id])
        chosen = choices.get(row.api_id)
        candidates = [r for r in options if r.key == chosen] if chosen else [r for r in options if r.kind != "mpf" and r.key != "mpf"]
        if len(candidates) != 1 or candidates[0].key == "mpf":
            if options:
                ambiguous[key] = "Выберите рецепт: " + ", ".join(r.key for r in options)
            continue
        recipe = candidates[0]
        output = recipe.output_quantity
        if recipe.output_unit in {"crate", "vehicle_crate", "equipment_crate"}:
            output *= row.vehicle_crate_size if row.is_equipment else row.crate_size
        recipes[key] = replace(recipe, output_quantity=output, output_unit="item")
    for method in result["methods"]:
        try:
            raw = expand_resources(method["materials"], recipes)
            method["base_resources"] = raw
            method["unresolved_resources"] = {k: ambiguous[k] for k in raw if k in ambiguous}
        except ProductionChainError as exc:
            method["base_resources"] = None
            method["unresolved_resources"] = {"chain": str(exc)}
    return result
