from __future__ import annotations

import logging
from typing import Any

from config import config
from services.foxhole_types import OrderItem, ParsedOrder
from services.resource_cost_formatter import ResourceCostFormatter

logger = logging.getLogger(__name__)


class NormalizedOrderBuilder:
    """Builds user-facing order text from resolved items or stored snapshots."""

    @staticmethod
    def resources(cost: dict[str, int] | None, crate_sizes: dict[str, int]) -> str:
        return ResourceCostFormatter(
            crate_sizes,
            config.FOXHOLE_RESOURCE_COST_DISPLAY,
            compact=True,
        ).materials(cost)

    @staticmethod
    def site_ru(site: str | None) -> str:
        return {
            "factory": "фабрике",
            "garage": "гараже",
            "shipyard": "верфи",
            "construction yard": "строительном дворе",
        }.get((site or "").casefold(), site or "производстве")

    def format_item(self, order_item: OrderItem, *, preview: bool = False) -> str:
        item = order_item.resolved.item
        is_equipment = item.is_equipment
        unit = "шт." if is_equipment else "ящиков"
        standard = self.resources(order_item.factory_cost, item.resource_crate_sizes)
        suffix = "за шт." if is_equipment else "за ящ"
        standard_text = f"{standard} {suffix}"
        mpf_text = (
            f"{self.resources(order_item.mpf_cost, item.resource_crate_sizes)} "
            f"на MPF за {order_item.mpf_crates} ящ"
            if order_item.mpf_cost
            else "MPF недоступно"
        )
        marker = ""
        if preview:
            marker = "⚠️ " if order_item.resolved.requires_confirmation else "✅ "
        rendered = (
            f"{marker}**{item.ru_name}** — {order_item.quantity} {unit}\n"
            f"({standard_text} / {mpf_text})"
        )
        logger.debug(
            "[MPF DEBUG] item=%s value_passed=%s rendered=%s",
            item.api_id,
            order_item.mpf_cost,
            rendered,
        )
        return rendered

    def format_order(self, order: ParsedOrder, *, preview: bool = False) -> str:
        lines = [self.format_item(item, preview=preview) for item in order.items]
        for unresolved in order.unresolved:
            lines.append(f"❓ Не удалось определить «{unresolved.line.query}»")
        return "\n\n".join(lines) or "В заказе не найдено позиций с названием и количеством."

    def format_snapshot(self, row: Any) -> str:
        if isinstance(row, dict):
            name = row["display_name"]
            quantity = row["quantity"]
            unit = row["unit"]
            snapshot = row.get("cost_snapshot") or {}
        else:
            name = row.display_name
            quantity = row.quantity
            unit = row.unit
            snapshot = row.cost_snapshot or {}

        is_equipment = unit == "item"
        unit_label = "шт." if is_equipment else "ящиков"
        crate_sizes = snapshot.get("resource_crate_sizes") or {}
        standard = self.resources(snapshot.get("factory"), crate_sizes)
        suffix = "за шт." if is_equipment else "за ящ"
        mpf_crates = snapshot.get("mpf_crates", 0)
        mpf_text = (
            f"{self.resources(snapshot.get('mpf'), crate_sizes)} на MPF за {mpf_crates} "
            f"ящ"
            if mpf_crates
            else "MPF недоступно"
        )
        rendered = (
            f"• **{name}** — {quantity} {unit_label}\n"
            f"  ({standard} {suffix} / {mpf_text})"
        )
        logger.debug(
            "[MPF DEBUG] snapshot_name=%s value_passed=%s rendered=%s",
            name,
            snapshot.get("mpf"),
            rendered,
        )
        return rendered

    def format_snapshots(self, rows: list | None) -> str:
        return "\n\n".join(self.format_snapshot(row) for row in rows or [])

    @staticmethod
    def split_fields(text: str, limit: int = 1024) -> list[str]:
        if not text:
            return []
        fields: list[str] = []
        current = ""
        for block in text.split("\n\n"):
            candidate = f"{current}\n\n{block}" if current else block
            if len(candidate) <= limit:
                current = candidate
                continue
            if current:
                fields.append(current)
            while len(block) > limit:
                fields.append(block[:limit])
                block = block[limit:]
            current = block
        if current:
            fields.append(current)
        return fields
