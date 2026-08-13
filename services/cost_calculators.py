from __future__ import annotations

import math

from services.foxhole_types import CatalogItem


def _positive_cost(cost: dict[str, int | float]) -> dict[str, int]:
    return {key.casefold(): int(value) for key, value in cost.items() if value and value > 0}


class ProductionCostCalculator:
    def reference_cost(self, item: CatalogItem) -> dict[str, int]:
        return _positive_cost(item.factory_cost)

    def order_cost(self, item: CatalogItem, quantity: int) -> dict[str, int]:
        multiplier = quantity
        return {resource: amount * multiplier for resource, amount in self.reference_cost(item).items()}


class MPFCostCalculator:
    @staticmethod
    def _discounted_total(base_per_crate: int, crates: int) -> int:
        # FoxholeHQ applies 90%, 80%, ... 50% and rounds every queue up.
        return sum(
            math.ceil(base_per_crate * max(0.5, 0.9 - 0.1 * index))
            for index in range(crates)
        )

    def reference_cost(self, item: CatalogItem) -> tuple[dict[str, int], int]:
        if not item.mpf_available:
            return {}, 0
        crates = max(3, item.mpf_max_crates)
        base_cost = item.mpf_base_cost or {
            resource: amount * (item.vehicle_crate_size if item.is_vehicle else 1)
            for resource, amount in _positive_cost(item.factory_cost).items()
        }
        result = {
            resource: self._discounted_total(amount, crates)
            for resource, amount in _positive_cost(base_cost).items()
        }
        return result, crates


class OrderCostCalculator:
    def __init__(self) -> None:
        self.production = ProductionCostCalculator()

    def total_standard(self, items: list[tuple[CatalogItem, int]]) -> dict[str, int]:
        total: dict[str, int] = {}
        for item, quantity in items:
            for resource, amount in self.production.order_cost(item, quantity).items():
                total[resource] = total.get(resource, 0) + amount
        return total
