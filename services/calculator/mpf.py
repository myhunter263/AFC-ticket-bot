from __future__ import annotations

import math

from services.calculator.models import ProductionCalculation, RecipeInput


class MPFCalculator:
    MIN_CRATES = 3

    @staticmethod
    def split_queues(crate_count: int, max_crates: int) -> list[int]:
        if crate_count <= 0:
            raise ValueError("Количество MPF-ящиков должно быть положительным.")
        if max_crates < MPFCalculator.MIN_CRATES:
            raise ValueError("Максимальная MPF-партия меньше минимальной.")
        target = max(MPFCalculator.MIN_CRATES, crate_count)
        queues: list[int] = []
        while target > max_crates:
            queues.append(max_crates)
            target -= max_crates
        if target and target < MPFCalculator.MIN_CRATES and queues:
            needed = MPFCalculator.MIN_CRATES - target
            queues[-1] -= needed
            target += needed
        if target:
            queues.append(target)
        if any(value < MPFCalculator.MIN_CRATES or value > max_crates for value in queues):
            raise ValueError("Количество нельзя разбить на допустимые MPF-партии.")
        return queues

    @staticmethod
    def queue_cost(materials: dict[str, int | float], crates: int) -> dict[str, int | float]:
        total: dict[str, int | float] = {}
        for resource, base in materials.items():
            value = sum(
                (base * max(50, 100 - position * 10)) // 100
                if isinstance(base, int)
                else math.floor(base * max(50, 100 - position * 10) / 100)
                for position in range(1, crates + 1)
            )
            total[resource] = value
        return total

    @classmethod
    def calculate(
        cls,
        recipe: RecipeInput,
        *,
        amount: int,
        calculation_unit: str,
        crate_size: int,
        vehicles_per_crate: int,
        max_crates: int,
    ) -> ProductionCalculation:
        if amount <= 0:
            raise ValueError("Количество должно быть больше нуля.")
        requested_crates = amount
        if calculation_unit == "item":
            requested_crates = math.ceil(amount / max(1, vehicles_per_crate))
        queues = cls.split_queues(requested_crates, max_crates)
        materials: dict[str, int | float] = {}
        for queue in queues:
            for resource, value in cls.queue_cost(recipe.materials, queue).items():
                materials[resource] = materials.get(resource, 0) + value
        actual_crates = sum(queues)
        actual_output = (
            actual_crates * max(1, vehicles_per_crate)
            if calculation_unit == "item"
            else actual_crates
        )
        notes = [f"MPF-очереди: {' + '.join(map(str, queues))} ящ."]
        if actual_output > amount:
            unit = "шт." if calculation_unit == "item" else "ящ."
            notes.append(f"Фактический выпуск: {actual_output} {unit}; избыток: {actual_output - amount}.")
        return ProductionCalculation(
            recipe_key=recipe.key,
            building=recipe.building,
            kind="mpf",
            materials=materials,
            batches=actual_crates,
            requested_amount=amount,
            requested_unit=calculation_unit,
            actual_output=actual_output,
            output_unit="item" if calculation_unit == "item" else "crate",
            source=recipe.source,
            source_version=recipe.source_version,
            notes=notes,
            queues=queues,
            material_labels=dict(recipe.raw_data.get("material_labels") or {}),
        )
