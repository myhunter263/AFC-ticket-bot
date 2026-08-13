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
    def price_resources(cost: dict[str, int] | None, crate_sizes: dict[str, int]) -> str:
        return ResourceCostFormatter(crate_sizes).price_materials(cost)

    @staticmethod
    def site_ru(site: str | None) -> str:
        return {
            "factory": "\u0444\u0430\u0431\u0440\u0438\u043a\u0435",
            "garage": "\u0433\u0430\u0440\u0430\u0436\u0435",
            "shipyard": "\u0432\u0435\u0440\u0444\u0438",
            "construction yard": "\u0441\u0442\u0440\u043e\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u043c \u0434\u0432\u043e\u0440\u0435",
        }.get(
            (site or "").casefold(),
            site or "\u043f\u0440\u043e\u0438\u0437\u0432\u043e\u0434\u0441\u0442\u0432\u0435",
        )

    @staticmethod
    def _price_lines(
        *,
        name: str,
        is_equipment: bool,
        factory_cost: dict[str, int] | None,
        mpf_cost: dict[str, int] | None,
        mpf_crates: int,
        crate_sizes: dict[str, int],
    ) -> tuple[str, str]:
        factory_unit = (
            "[1 \u0448\u0442.]"
            if is_equipment
            else "[:package:1 \u044f\u0449.]"
        )
        factory = NormalizedOrderBuilder.price_resources(factory_cost, crate_sizes)
        fac_line = f":house: Fac - {factory} \u0437\u0430 {factory_unit} {name}"
        if mpf_cost and mpf_crates:
            mpf = NormalizedOrderBuilder.price_resources(mpf_cost, crate_sizes)
            mpf_line = (
                f":factory: MPF - {mpf} \u0437\u0430 "
                f"[:package:{mpf_crates} \u044f\u0449.] {name}"
            )
        else:
            mpf_line = ":factory: MPF - \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u043e"
        return fac_line, mpf_line

    def format_item(self, order_item: OrderItem, *, preview: bool = False) -> str:
        item = order_item.resolved.item
        is_equipment = item.is_equipment
        unit = "\u0448\u0442." if is_equipment else "\u044f\u0449\u0438\u043a\u043e\u0432"
        marker = ""
        if preview:
            marker = "\u26a0\ufe0f " if order_item.resolved.requires_confirmation else "\u2705 "
        fac_line, mpf_line = self._price_lines(
            name=item.ru_name,
            is_equipment=is_equipment,
            factory_cost=order_item.factory_cost,
            mpf_cost=order_item.mpf_cost,
            mpf_crates=order_item.mpf_crates,
            crate_sizes=item.resource_crate_sizes,
        )
        rendered = (
            f"{marker}{item.ru_name} \u2014 {order_item.quantity} {unit}\n\n"
            f"{fac_line}\n"
            f"{mpf_line}"
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
            lines.append(
                f"\u2753 \u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u043f\u0440\u0435\u0434\u0435\u043b\u0438\u0442\u044c "
                f"\u00ab{unresolved.line.query}\u00bb"
            )
        return "\n\n".join(lines) or (
            "\u0412 \u0437\u0430\u043a\u0430\u0437\u0435 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e \u043f\u043e\u0437\u0438\u0446\u0438\u0439 "
            "\u0441 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435\u043c \u0438 \u043a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432\u043e\u043c."
        )

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
        unit_label = "\u0448\u0442." if is_equipment else "\u044f\u0449\u0438\u043a\u043e\u0432"
        crate_sizes = snapshot.get("resource_crate_sizes") or {}
        fac_line, mpf_line = self._price_lines(
            name=name,
            is_equipment=is_equipment,
            factory_cost=snapshot.get("factory"),
            mpf_cost=snapshot.get("mpf"),
            mpf_crates=snapshot.get("mpf_crates", 0),
            crate_sizes=crate_sizes,
        )
        rendered = (
            f"{name} \u2014 {quantity} {unit_label}\n\n"
            f"{fac_line}\n"
            f"{mpf_line}"
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
