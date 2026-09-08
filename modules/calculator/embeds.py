from __future__ import annotations

import discord

from config import config
from services.calculator.models import ItemCalculation, ProductionCalculation


def _number(value: int | float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def resource_lines(
    materials: dict[str, int | float], labels: dict[str, str] | None = None
) -> str:
    custom = labels or {}
    return "\n".join(
        f"• **{custom.get(key) or config.FOXHOLE_RESOURCE_LABELS.get(key, key.replace('_', ' ').title())}:** {_number(value)}"
        for key, value in sorted(materials.items())
    ) or "• Ресурсы не указаны"


def method_embed(result: ItemCalculation, method: ProductionCalculation, index: int, total: int) -> discord.Embed:
    unit = "ящ." if result.requested_unit == "crate" else "шт."
    embed = discord.Embed(
        title=f"Производство: {result.name}",
        description=(
            f"Запрошено: **{result.requested_amount} {unit}**\n"
            f"Способ {index}/{total}: **{method.building}**"
        ),
        color=0x5865F2,
    )
    embed.add_field(
        name="Необходимые ресурсы",
        value=resource_lines(method.materials, method.material_labels)[:1024],
        inline=False,
    )
    output_label = "ящ." if method.output_unit in {"crate", "vehicle_crate", "equipment_crate"} else "шт."
    embed.add_field(
        name="Выпуск",
        value=f"**{method.actual_output} {output_label}** · производственных циклов: **{method.batches}**",
        inline=False,
    )
    if method.reference_costs:
        for size, costs in method.reference_costs.items():
            embed.add_field(
                name=f"MPF · {size} ящ.",
                value=resource_lines(costs, method.material_labels)[:1024],
                inline=True,
            )
    if method.notes:
        embed.add_field(name="Примечание", value="\n".join(method.notes)[:1024], inline=False)
    if method.base_resources:
        embed.add_field(name="Развёртка ресурсов", value=resource_lines(method.base_resources)[:1024], inline=False)
    if method.unresolved_resources:
        embed.add_field(name="Нужно уточнить цепочку", value="\n".join(f"{k}: {v}" for k, v in method.unresolved_resources.items())[:1024], inline=False)
    if result.unavailable_methods:
        embed.add_field(
            name="Без подтверждённой стоимости",
            value="\n".join(f"• {name}" for name in result.unavailable_methods)[:1024],
            inline=False,
        )
    if result.image_url:
        embed.set_thumbnail(url=result.image_url)
    embed.set_footer(text=f"Источник: {method.source} · {method.source_version or 'версия не указана'}")
    return embed


def calculation_embeds(result: ItemCalculation) -> list[discord.Embed]:
    if not result.methods:
        embed = discord.Embed(
            title=f"Производство: {result.name}",
            description="Для предмета нет подтверждённых рецептов.",
            color=0xFEE75C,
        )
        if result.unavailable_methods:
            embed.add_field(
                name="Известные способы без стоимости",
                value="\n".join(f"• {row}" for row in result.unavailable_methods),
                inline=False,
            )
        return [embed]
    return [
        method_embed(result, method, index, len(result.methods))
        for index, method in enumerate(result.methods, start=1)
    ]
