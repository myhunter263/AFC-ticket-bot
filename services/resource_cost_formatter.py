from __future__ import annotations

import math

from config import config


def calculate_required_resource_crates(
    resource_amount: int,
    resource_crate_size: int,
) -> int:
    if resource_amount < 0:
        raise ValueError("resource_amount cannot be negative")
    if resource_crate_size <= 0:
        raise ValueError("resource_crate_size must be positive")
    if resource_amount == 0:
        return 0
    return math.ceil(resource_amount / resource_crate_size)


class ResourceCostFormatter:
    def __init__(self, crate_sizes: dict[str, int], display: str = "both") -> None:
        self.crate_sizes = crate_sizes
        self.display = display if display in {"raw", "crate", "both"} else "both"

    @staticmethod
    def _crate_word(count: int) -> str:
        remainder_100 = count % 100
        remainder_10 = count % 10
        if 11 <= remainder_100 <= 14:
            return "ящиков"
        if remainder_10 == 1:
            return "ящик"
        if 2 <= remainder_10 <= 4:
            return "ящика"
        return "ящиков"

    def resource(self, resource: str, amount: int) -> str:
        label = config.FOXHOLE_RESOURCE_LABELS.get(resource, resource.upper())
        raw = f"{amount:,} {label}".replace(",", " ")
        crate_size = self.crate_sizes.get(resource)
        if self.display == "raw" or not crate_size:
            return raw
        crates = calculate_required_resource_crates(amount, crate_size)
        crated = f"{crates} {self._crate_word(crates)} {label}"
        if self.display == "crate":
            return crated
        return f"{raw} или {crated}"

    def materials(self, materials: dict[str, int] | None) -> str:
        if not materials:
            return "недоступно"
        return " + ".join(
            self.resource(resource, amount) for resource, amount in materials.items()
        )
