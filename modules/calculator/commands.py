from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from database.models import FoxholeRecipeOverride
from database.session import async_session_maker
from modules.calculator.admin import CalculatorAdminView
from modules.calculator.embeds import calculation_embeds
from modules.calculator.views import CalculatorPaginationView, TrainBuilderView
from services.calculator.service import CalculatorService
from services.calculator.models import ItemCalculation, ProductionCalculation
from integrations.backend.client import BackendError
from services.foxhole_types import ResolvedItem
from services.item_catalog_service import ItemCatalogService
from services.item_resolver import ItemResolver
from services.item_sync_service import ItemSyncService
from utils.embeds import EmbedBuilder
from utils.permissions import PermissionChecker


class CalculatorCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def item_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if not interaction.guild_id:
            return []
        async with async_session_maker() as session:
            if current.strip():
                rows = await ItemCatalogService.search(session, interaction.guild_id, current, 25)
                items = [(row.item_id, row.ru_name or row.item.api_name, row.item.api_name) for row in rows]
            else:
                catalog = await ItemCatalogService.get_catalog(session, interaction.guild_id)
                items = [(row.id, row.ru_name, row.api_name) for row in catalog[:25]]
        return [
            app_commands.Choice(
                name=(name if name == api_name else f"{name} · {api_name}")[:100],
                value=f"id:{item_id}",
            )
            for item_id, name, api_name in items if item_id is not None
        ][:25]

    async def _resolve(self, guild_id: int, query: str):
        async with async_session_maker() as session:
            catalog = await ItemCatalogService.get_catalog(session, guild_id)
            if query.startswith("id:") and query[3:].isdigit():
                item = next((row for row in catalog if row.id == int(query[3:])), None)
                return item, []
            resolved = ItemResolver(catalog).resolve(query)
            if isinstance(resolved, ResolvedItem):
                return resolved.item, []
            return None, [row.item for row in resolved.candidates]

    @app_commands.command(name="calc", description="Рассчитать производство предмета Foxhole")
    @app_commands.guild_only()
    @app_commands.describe(item="Предмет, русское название или алиас", amount="Количество ящиков или штук")
    @app_commands.autocomplete(item=item_autocomplete)
    async def calculate(
        self, interaction: discord.Interaction, item: str,
        amount: app_commands.Range[int, 1, 100000] = 1,
    ) -> None:
        await interaction.response.defer(thinking=True)
        selected, candidates = await self._resolve(interaction.guild_id, item)
        if selected is None:
            suggestions = "\n".join(f"• {row.ru_name} (`{row.api_name}`)" for row in candidates)
            await interaction.followup.send(
                embed=EmbedBuilder.warning(
                    "Предмет не найден" if not candidates else "Уточните предмет",
                    suggestions or f"Нет совпадений для `{item}`.",
                ), ephemeral=True,
            )
            return
        try:
            crm = self.bot.get_cog("OrdersCog")
            if crm and crm.guild_id == interaction.guild_id:
                payload = await crm.client.request("POST", "/api/v1/catalog/calculate", member=interaction.user,
                    data={"item_id": selected.id, "quantity": amount, "unit": CalculatorService.calculation_unit(selected)})
            else:
                from services.calculator.planning import calculate_plan
                async with async_session_maker() as session:
                    catalog = await ItemCatalogService.get_catalog(session, interaction.guild_id)
                    overrides = list((await session.scalars(select(FoxholeRecipeOverride).where(
                        FoxholeRecipeOverride.guild_id == interaction.guild_id,
                    ))).all())
                payload = calculate_plan(selected, amount, catalog, overrides)
            result = ItemCalculation(**{**payload, "methods": [ProductionCalculation(**m) for m in payload["methods"]]})
        except (ValueError, BackendError) as exc:
            await interaction.followup.send(embed=EmbedBuilder.error("Расчёт невозможен", str(exc)), ephemeral=True)
            return
        embeds = calculation_embeds(result)
        view = CalculatorPaginationView(interaction.user.id, embeds) if len(embeds) > 1 else None
        await interaction.followup.send(embed=embeds[0], view=view)

    @app_commands.command(name="train", description="Собрать и рассчитать железнодорожный состав")
    @app_commands.guild_only()
    async def train(self, interaction: discord.Interaction) -> None:
        async with async_session_maker() as session:
            catalog = await ItemCatalogService.get_catalog(session, interaction.guild_id)
        items = [
            item for item in catalog
            if str(item.metadata.get("mobility") or (item.metadata.get("foxholewiki") or {}).get("mobility") or "").casefold() == "largerail"
        ]
        if not items:
            await interaction.response.send_message(
                embed=EmbedBuilder.warning("Данные поездов не загружены", "Администратору нужно обновить каталог калькулятора."),
                ephemeral=True,
            )
            return
        view = TrainBuilderView(interaction.user.id, interaction.guild_id, items)
        await interaction.response.send_message(embed=view.embed(), view=view)

    @app_commands.command(name="calc-admin", description="Администрирование Foxhole-калькулятора")
    @app_commands.guild_only()
    async def calc_admin(self, interaction: discord.Interaction) -> None:
        async with async_session_maker() as session:
            if not await PermissionChecker.is_bot_admin(interaction, session):
                await interaction.response.send_message("Нет доступа.", ephemeral=True)
                return
            status = await ItemSyncService.status(session, interaction.guild_id)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Foxhole Calculator",
                description=(
                    f"Версия: **{status['source_version'] or 'не загружена'}**\n"
                    f"Предметов: **{status['item_count']}** · рецептов: **{status['recipe_count']}**\n"
                    f"Последняя ошибка: {(status['last_error'] or 'нет')[:500]}"
                ), color=0x5865F2,
            ),
            view=CalculatorAdminView(interaction.guild_id), ephemeral=True,
        )

    @app_commands.command(name="calc-debug", description="Диагностика рецептов калькулятора")
    @app_commands.guild_only()
    @app_commands.autocomplete(item=item_autocomplete)
    async def calc_debug(self, interaction: discord.Interaction, item: str) -> None:
        async with async_session_maker() as session:
            if not await PermissionChecker.is_bot_admin(interaction, session):
                await interaction.response.send_message("Нет доступа.", ephemeral=True)
                return
        selected, candidates = await self._resolve(interaction.guild_id, item)
        if selected is None:
            await interaction.response.send_message("Предмет не найден.", ephemeral=True)
            return
        async with async_session_maker() as session:
            overrides = list((await session.execute(select(FoxholeRecipeOverride).where(
                FoxholeRecipeOverride.guild_id == interaction.guild_id,
                FoxholeRecipeOverride.item_id == selected.id,
            ))).scalars().all())
        lines = [
            f"`{key}` · {data.get('building') or data.get('method')} · "
            f"{data.get('materials')} · {data.get('source')} {data.get('source_version') or ''}"
            for key, data in selected.recipe_details.items()
        ]
        lines.extend(
            f"`{row.production_method}` · {row.building or 'manual'} · "
            f"{row.materials} · manual_override"
            for row in overrides
        )
        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"Calculator debug · {selected.ru_name}",
                description=(
                    f"Internal ID: `{selected.id}`\nUpstream ID: `{selected.api_id}`\n"
                    f"Category: `{selected.category}` · unit: `{CalculatorService.calculation_unit(selected)}`\n"
                    f"Crate size: `{selected.crate_size}`\nSource: `{selected.source} {selected.source_version or ''}`\n\n"
                    f"Cache updated: `{selected.synced_at or '—'}`\n"
                    f"Raw methods: `{selected.metadata.get('production_methods') or []}`\n\n"
                    + ("\n".join(lines) or "Рецептов нет")
                )[:4096], color=0x5865F2,
            ), ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CalculatorCog(bot))
