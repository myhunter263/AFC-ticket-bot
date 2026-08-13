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
    def __init__(
        self,
        crate_sizes: dict[str, int],
        display: str = "both",
        compact: bool = False,
    ) -> None:
        self.crate_sizes = crate_sizes
        self.display = display if display in {"raw", "crate", "both"} else "both"
        self.compact = compact

    @staticmethod
    def _crate_word(count: int) -> str:
        remainder_100 = count % 100
        remainder_10 = count % 10
        if 11 <= remainder_100 <= 14:
            return "\u044f\u0449\u0438\u043a\u043e\u0432"
        if remainder_10 == 1:
            return "\u044f\u0449\u0438\u043a"
        if 2 <= remainder_10 <= 4:
            return "\u044f\u0449\u0438\u043a\u0430"
        return "\u044f\u0449\u0438\u043a\u043e\u0432"

    @staticmethod
    def _raw(resource: str, amount: int) -> str:
        label = config.FOXHOLE_RESOURCE_LABELS.get(resource, resource.upper())
        return f"{amount:,} {label}".replace(",", " ")

    def resource(self, resource: str, amount: int) -> str:
        label = config.FOXHOLE_RESOURCE_LABELS.get(resource, resource.upper())
        raw = self._raw(resource, amount)
        crate_size = self.crate_sizes.get(resource)
        if self.display == "raw" or not crate_size:
            return raw
        crates = calculate_required_resource_crates(amount, crate_size)
        crate_word = "\u044f\u0449" if self.compact else self._crate_word(crates)
        crated = f"{crates} {crate_word} {label}"
        if self.display == "crate":
            return crated
        return f"{raw} \u0438\u043b\u0438 {crated}"

    def materials(self, materials: dict[str, int] | None) -> str:
        if not materials:
            return "\u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u043e"
        if self.compact and self.display == "both":
            raw = " + ".join(self._raw(resource, amount) for resource, amount in materials.items())
            crated = " + ".join(
                self.resource(resource, amount).split(" \u0438\u043b\u0438 ")[-1]
                for resource, amount in materials.items()
            )
            return f"{raw} \u0438\u043b\u0438 {crated}"
        return " + ".join(
            self.resource(resource, amount) for resource, amount in materials.items()
        )

    def price_materials(self, materials: dict[str, int] | None) -> str:
        """Render the canonical raw/[crate] price for each recipe resource."""
        if not materials:
            return "\u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u043e"

        rendered: list[str] = []
        for resource, amount in materials.items():
            label = config.FOXHOLE_RESOURCE_LABELS.get(resource, resource.upper())
            raw = self._raw(resource, amount)
            crate_size = self.crate_sizes.get(resource)
            if not crate_size:
                rendered.append(raw)
                continue
            crates = calculate_required_resource_crates(amount, crate_size)
            rendered.append(f"{raw}/[:package:{crates} \u044f\u0449.] {label}")
        return " + ".join(rendered)
