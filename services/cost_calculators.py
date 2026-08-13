from __future__ import annotations

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
    def material_breakdown(base_per_crate: int, crates: int) -> list[dict[str, int]]:
        if base_per_crate < 0 or crates < 0:
            raise ValueError("MPF base cost and crate count cannot be negative")
        return [
            {
                "position": position,
                "percent": max(50, 100 - position * 10),
                "cost": base_per_crate * max(50, 100 - position * 10) // 100,
            }
            for position in range(1, crates + 1)
        ]

    @classmethod
    def calculate_mpf_material_cost(cls, base_per_crate: int, crates: int) -> int:
        return sum(row["cost"] for row in cls.material_breakdown(base_per_crate, crates))

    @classmethod
    def calculate_mpf_cost(
        cls,
        base_cost: dict[str, int],
        crate_count: int,
    ) -> dict[str, int]:
        return {
            resource: cls.calculate_mpf_material_cost(amount, crate_count)
            for resource, amount in _positive_cost(base_cost).items()
        }

    def reference_cost(self, item: CatalogItem) -> tuple[dict[str, int], int]:
        if not item.mpf_available:
            return {}, 0
        crates = max(3, item.mpf_max_crates)
        base_cost = item.mpf_base_cost or {
            resource: amount * (item.vehicle_crate_size if item.is_vehicle else 1)
            for resource, amount in _positive_cost(item.factory_cost).items()
        }
        return self.calculate_mpf_cost(base_cost, crates), crates


class OrderCostCalculator:
    def __init__(self) -> None:
        self.production = ProductionCostCalculator()

    def total_standard(self, items: list[tuple[CatalogItem, int]]) -> dict[str, int]:
        total: dict[str, int] = {}
        for item, quantity in items:
            for resource, amount in self.production.order_cost(item, quantity).items():
                total[resource] = total.get(resource, 0) + amount
        return total
