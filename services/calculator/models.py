from __future__ import annotations

from dataclasses import dataclass, field


Number = int | float


@dataclass(slots=True)
class RecipeInput:
    key: str
    building: str
    kind: str
    output_quantity: int
    output_unit: str
    materials: dict[str, Number]
    source: str
    source_version: str | None = None
    raw_data: dict = field(default_factory=dict)


@dataclass(slots=True)
class ProductionCalculation:
    recipe_key: str
    building: str
    kind: str
    materials: dict[str, Number]
    batches: int
    requested_amount: int
    requested_unit: str
    actual_output: int
    output_unit: str
    source: str
    source_version: str | None = None
    notes: list[str] = field(default_factory=list)
    queues: list[int] = field(default_factory=list)
    material_labels: dict[str, str] = field(default_factory=dict)
    reference_costs: dict[int, dict[str, Number]] = field(default_factory=dict)


@dataclass(slots=True)
class ItemCalculation:
    item_id: int | None
    name: str
    api_name: str
    requested_amount: int
    requested_unit: str
    crate_size: int
    image_url: str | None
    methods: list[ProductionCalculation]
    unavailable_methods: list[str] = field(default_factory=list)
