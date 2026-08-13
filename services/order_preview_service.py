from __future__ import annotations

import logging

from config import config
from services.cost_calculators import MPFCostCalculator, ProductionCostCalculator
from services.foxhole_types import (
    CatalogItem,
    OrderItem,
    ParsedOrder,
    ResolvedItem,
    ResolvedItemCandidates,
    UnresolvedOrderItem,
)
from services.item_resolver import ItemResolver
from services.order_parser import OrderParser

logger = logging.getLogger(__name__)


class OrderPreviewService:
    def __init__(self, catalog: list[CatalogItem]) -> None:
        self.catalog = catalog
        self.resolver = ItemResolver(catalog)
        self.parser = OrderParser()
        self.production = ProductionCostCalculator()
        self.mpf = MPFCostCalculator()

    def parse(self, text: str) -> ParsedOrder:
        items: list[OrderItem] = []
        unresolved: list[UnresolvedOrderItem] = []
        for line in self.parser.parse(text):
            result = self.resolver.resolve(line.query)
            if isinstance(result, ResolvedItemCandidates):
                unresolved.append(UnresolvedOrderItem(line=line, result=result))
                continue
            items.append(self._make_item(line.quantity, line.query, result))
        return ParsedOrder(items=items, unresolved=unresolved)

    def choose_candidate(self, order: ParsedOrder, unresolved_index: int, item_id: int) -> None:
        unresolved = order.unresolved.pop(unresolved_index)
        candidate = next(
            (candidate for candidate in unresolved.result.candidates if candidate.item.id == item_id),
            None,
        )
        if candidate is None:
            item = next((item for item in self.catalog if item.id == item_id), None)
            if item is None:
                raise ValueError("Выбранный предмет не найден в каталоге.")
            candidate = ResolvedItem(item, 100, "manual", unresolved.line.query, False)
        else:
            candidate = ResolvedItem(candidate.item, 100, "manual", candidate.matched_text, False)
        logger.info(
            "Manual Foxhole item selection: %r -> %s",
            unresolved.line.query,
            candidate.item.api_name,
        )
        order.items.append(self._make_item(unresolved.line.quantity, unresolved.line.query, candidate))

    def _make_item(self, quantity: int, query: str, resolved: ResolvedItem) -> OrderItem:
        item = resolved.item
        mpf_cost, mpf_crates = self.mpf.reference_cost(item)
        return OrderItem(
            quantity=quantity,
            unit="item" if item.is_vehicle else "crate",
            query=query,
            resolved=resolved,
            factory_cost=self.production.reference_cost(item),
            mpf_cost=mpf_cost,
            mpf_crates=mpf_crates,
        )

    @staticmethod
    def _resources(cost: dict[str, int]) -> str:
        if not cost:
            return "недоступно"
        return ", ".join(
            f"{amount:,} {config.FOXHOLE_RESOURCE_LABELS.get(resource, resource.upper())}".replace(",", " ")
            for resource, amount in cost.items()
        )

    def format_item(self, order_item: OrderItem) -> str:
        item = order_item.resolved.item
        unit = "шт." if item.is_vehicle else "ящиков"
        standard = self._resources(order_item.factory_cost)
        if item.is_vehicle:
            standard_text = f"{standard} в {self._site_ru(item.factory_site)} за шт."
        else:
            standard_text = f"{standard} на {self._site_ru(item.factory_site)} за ящик"
        if order_item.mpf_cost:
            mpf_text = f"{self._resources(order_item.mpf_cost)} на MPF за {order_item.mpf_crates} ящиков"
        else:
            mpf_text = "MPF недоступно"
        marker = "⚠️" if order_item.resolved.requires_confirmation else "✅"
        return (
            f"{marker} **{item.ru_name}** — {order_item.quantity} {unit}\n"
            f"({standard_text} / {mpf_text})"
        )

    def format_order(self, order: ParsedOrder) -> str:
        lines = [self.format_item(item) for item in order.items]
        for unresolved in order.unresolved:
            lines.append(f"❓ Не удалось определить «{unresolved.line.query}»")
        return "\n\n".join(lines) or "В заказе не найдено позиций вида «количество + название»."

    @staticmethod
    def _site_ru(site: str | None) -> str:
        return {"factory": "фабрике", "garage": "гараже"}.get((site or "").casefold(), site or "производстве")

    def snapshots(self, order: ParsedOrder) -> list[dict]:
        return [
            {
                "item_id": row.resolved.item.id,
                "quantity": row.quantity,
                "unit": row.unit,
                "query": row.query,
                "display_name": row.resolved.item.ru_name,
                "confidence": row.resolved.confidence,
                "matched_by": row.resolved.matched_by,
                "cost_snapshot": {
                    "item_display_name": row.resolved.item.ru_name,
                    "factory": row.factory_cost,
                    "factory_site": row.resolved.item.factory_site,
                    "mpf": row.mpf_cost,
                    "mpf_crates": row.mpf_crates,
                    "crate_size": row.resolved.item.crate_size,
                    "vehicle_crate_size": row.resolved.item.vehicle_crate_size,
                    "source": row.resolved.item.source,
                    "data_version": row.resolved.item.source_version,
                    "synced_at": (
                        row.resolved.item.synced_at.isoformat()
                        if hasattr(row.resolved.item.synced_at, "isoformat")
                        else row.resolved.item.synced_at
                    ),
                },
            }
            for row in order.items
        ]
