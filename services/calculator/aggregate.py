from __future__ import annotations

from services.calculator.models import Number, ProductionCalculation


def aggregate_resources(
    rows: list[tuple[ProductionCalculation, int]],
) -> dict[str, Number]:
    total: dict[str, Number] = {}
    for calculation, multiplier in rows:
        if multiplier < 0:
            raise ValueError("Множитель не может быть отрицательным.")
        for resource, amount in calculation.materials.items():
            total[resource] = total.get(resource, 0) + amount * multiplier
    return total

