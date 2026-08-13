from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CatalogItem:
    id: int | None
    api_id: str
    api_name: str
    ru_name: str
    aliases: list[str]
    alias_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    category: str | None = None
    is_vehicle: bool = False
    production_group: str = "auto"
    crate_size: int = 1
    vehicle_crate_size: int = 3
    factory_site: str | None = None
    factory_cost: dict[str, int] = field(default_factory=dict)
    mpf_base_cost: dict[str, int] = field(default_factory=dict)
    mpf_available: bool = False
    mpf_max_crates: int = 9
    source: str = "bundled"
    source_version: str | None = None
    synced_at: Any = None
    overrides: dict[str, Any] = field(default_factory=dict)
    resource_crate_sizes: dict[str, int] = field(default_factory=dict)
    recipe_details: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def is_equipment(self) -> bool:
        return self.production_group == "equipment" or (
            self.production_group == "auto" and self.is_vehicle
        )


@dataclass(slots=True)
class ResolvedItem:
    item: CatalogItem
    confidence: int
    matched_by: str
    matched_text: str
    requires_confirmation: bool = False


@dataclass(slots=True)
class ResolvedItemCandidates:
    query: str
    candidates: list[ResolvedItem]


@dataclass(slots=True)
class ParsedOrderLine:
    quantity: int
    requested_unit: str | None
    query: str


@dataclass(slots=True)
class OrderItem:
    quantity: int
    unit: str
    query: str
    resolved: ResolvedItem
    factory_cost: dict[str, int]
    mpf_cost: dict[str, int]
    mpf_crates: int


@dataclass(slots=True)
class ParsedOrder:
    items: list[OrderItem]
    unresolved: list["UnresolvedOrderItem"]

    @property
    def requires_confirmation(self) -> bool:
        return bool(self.unresolved) or any(
            item.resolved.requires_confirmation for item in self.items
        )


@dataclass(slots=True)
class UnresolvedOrderItem:
    line: ParsedOrderLine
    result: ResolvedItemCandidates
