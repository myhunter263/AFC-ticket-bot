from __future__ import annotations

import math

from services.calculator.models import ProductionCalculation, RecipeInput


class FactoryCalculator:
    @staticmethod
    def calculate(
        recipe: RecipeInput,
        *,
        amount: int,
        calculation_unit: str,
        crate_size: int,
        units_per_crate: int | None = None,
    ) -> ProductionCalculation:
        if amount <= 0:
            raise ValueError("Количество должно быть больше нуля.")
        crate_outputs = {"crate", "vehicle_crate", "equipment_crate"}
        target_output = amount
        output_quantity = max(1, recipe.output_quantity)
        result_unit = recipe.output_unit
        if calculation_unit == "item" and recipe.output_unit in crate_outputs:
            # Large items are requested as individual units even when their
            # Factory recipe produces complete crates.
            output_quantity *= max(1, units_per_crate or crate_size)
            result_unit = "item"
        elif calculation_unit == "crate" and recipe.output_unit not in crate_outputs:
            target_output *= max(1, crate_size)
        batches = math.ceil(target_output / output_quantity)
        materials = {
            key: value * batches for key, value in recipe.materials.items()
        }
        actual_output = batches * output_quantity
        notes: list[str] = []
        if actual_output > target_output:
            notes.append(f"Фактический выпуск: {actual_output}; избыток: {actual_output - target_output}.")
        return ProductionCalculation(
            recipe_key=recipe.key,
            building=recipe.building,
            kind=recipe.kind,
            materials=materials,
            batches=batches,
            requested_amount=amount,
            requested_unit=calculation_unit,
            actual_output=actual_output,
            output_unit=result_unit,
            source=recipe.source,
            source_version=recipe.source_version,
            notes=notes,
            material_labels=dict(recipe.raw_data.get("material_labels") or {}),
        )
