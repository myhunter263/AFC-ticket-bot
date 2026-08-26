from __future__ import annotations

import math
import re

import discord
from sqlalchemy import delete, select

from database.models import FoxholeRecipeOverride
from database.session import async_session_maker
from services.audit_service import AuditService
from services.item_catalog_service import ItemCatalogService
from services.item_sync_service import ItemSyncService
from services.item_resolver import ItemResolver
from utils.embeds import EmbedBuilder
from utils.permissions import PermissionChecker


def parse_materials(value: str) -> dict[str, int | float]:
    aliases = {
        "pcon": "processed_construction_materials",
        "pcmats": "processed_construction_materials",
        "cmat": "construction_materials",
        "am1": "assembly_materials_i",
        "am2": "assembly_materials_ii",
        "am3": "assembly_materials_iii",
        "am4": "assembly_materials_iv",
        "am5": "assembly_materials_v",
    }
    result: dict[str, int | float] = {}
    for part in value.split(","):
        if "=" not in part:
            raise ValueError("Формат ресурсов: pcon=90,assembly_materials_iv=25")
        key, raw = part.split("=", 1)
        key = re.sub(r"[^a-z0-9_]+", "_", key.strip().casefold()).strip("_")
        key = aliases.get(key, key)
        number = float(raw.strip())
        if not key or not math.isfinite(number) or number <= 0:
            raise ValueError("Название и количество ресурса должны быть положительными.")
        result[key] = int(number) if number.is_integer() else number
    return result


class CalculatorAdminView(discord.ui.View):
    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=300)
        self.guild_id = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        async with async_session_maker() as session:
            allowed = await PermissionChecker.is_bot_admin(interaction, session)
        if not allowed:
            await interaction.response.send_message("Нет доступа.", ephemeral=True)
        return allowed

    @discord.ui.button(label="Каталог и алиасы", style=discord.ButtonStyle.primary)
    async def catalog(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        from ui.views.item_catalog import ItemCatalogView

        await interaction.response.send_message(
            embed=EmbedBuilder.info("Каталог калькулятора", "Поиск, переводы и алиасы."),
            view=ItemCatalogView(self.guild_id), ephemeral=True,
        )

    @discord.ui.button(label="Обновить cache", style=discord.ButtonStyle.success)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with async_session_maker() as session:
            result = await ItemCatalogService.sync(session, self.guild_id)
            await session.commit()
        embed = (
            EmbedBuilder.success(
                "Cache обновлён",
                f"Версия: **{result.source_version}**\n"
                f"Предметов: **{result.item_count}** · рецептов: **{result.recipe_count}**",
            )
            if result.success
            else EmbedBuilder.warning(
                "Cache не обновлён",
                f"{result.error}\nИспользуются последние успешные данные.",
            )
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="Статус", style=discord.ButtonStyle.secondary)
    async def status(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            status = await ItemSyncService.status(session, self.guild_id)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Calculator cache status",
                description=(
                    f"Версия: **{status['source_version'] or 'нет'}**\n"
                    f"Последний success: **{status['last_success_at'] or 'нет'}**\n"
                    f"Предметов: **{status['item_count']}** · рецептов: **{status['recipe_count']}**\n"
                    f"Ошибка: {(status['last_error'] or 'нет')[:600]}"
                ), color=0x5865F2,
            ), ephemeral=True,
        )

    @discord.ui.button(label="Добавить override", style=discord.ButtonStyle.success)
    async def add_override(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(RecipeOverrideModal(self.guild_id))

    @discord.ui.button(label="Удалить override", style=discord.ButtonStyle.danger)
    async def remove_override(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(RemoveOverrideModal(self.guild_id))


async def resolve_item(session, guild_id: int, query: str):
    catalog = await ItemCatalogService.get_catalog(session, guild_id)
    if query.strip().isdigit():
        return next((item for item in catalog if item.id == int(query)), None)
    result = ItemResolver(catalog).resolve(query)
    return getattr(result, "item", None)


class RecipeOverrideModal(discord.ui.Modal, title="Recipe override"):
    item = discord.ui.TextInput(label="Предмет или ID", max_length=100)
    method = discord.ui.TextInput(label="Ключ метода", placeholder="facility_manual", max_length=50)
    building = discord.ui.TextInput(label="Здание", max_length=100)
    materials = discord.ui.TextInput(
        label="Ресурсы", placeholder="pcon=90,assembly_materials_iv=25", max_length=1000
    )
    output = discord.ui.TextInput(label="Выход и единица", placeholder="1,item", default="1,item", max_length=30)

    def __init__(self, guild_id: int) -> None:
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            materials = parse_materials(str(self.materials))
            output_quantity_text, output_unit = [x.strip() for x in str(self.output).split(",", 1)]
            output_quantity = int(output_quantity_text)
            if output_quantity < 1 or output_unit not in {"item", "crate"}:
                raise ValueError("Выход: положительное число и item/crate, например 1,item.")
        except (ValueError, TypeError) as exc:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Некорректный override", str(exc)), ephemeral=True
            )
            return
        async with async_session_maker() as session:
            item = await resolve_item(session, self.guild_id, str(self.item))
            if item is None:
                await interaction.response.send_message("Предмет не найден.", ephemeral=True)
                return
            method = str(self.method).strip().casefold().replace(" ", "_")
            method = re.sub(r"[^a-z0-9_]+", "_", method).strip("_")
            if not method:
                await interaction.response.send_message(
                    "Ключ метода не может быть пустым.", ephemeral=True
                )
                return
            row = await session.scalar(select(FoxholeRecipeOverride).where(
                FoxholeRecipeOverride.guild_id == self.guild_id,
                FoxholeRecipeOverride.item_id == item.id,
                FoxholeRecipeOverride.production_method == method,
            ))
            if row is None:
                row = FoxholeRecipeOverride(
                    guild_id=self.guild_id, item_id=item.id,
                    production_method=method, created_by=interaction.user.id,
                )
                session.add(row)
            row.building = str(self.building)
            row.materials = materials
            row.output_quantity = output_quantity
            row.output_unit = output_unit
            row.enabled = True
            await AuditService.log(
                session, guild_id=self.guild_id, user_id=interaction.user.id,
                user_name=str(interaction.user), action="CALCULATOR_OVERRIDE_UPDATED",
                target_type="FOXHOLE_ITEM", target_id=item.id,
                details={"method": method, "materials": materials},
            )
            await session.commit()
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Override сохранён", f"{item.ru_name} · {method}"), ephemeral=True
        )


class RemoveOverrideModal(discord.ui.Modal, title="Удалить recipe override"):
    item = discord.ui.TextInput(label="Предмет или ID", max_length=100)
    method = discord.ui.TextInput(label="Точный ключ метода", max_length=50)

    def __init__(self, guild_id: int) -> None:
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        async with async_session_maker() as session:
            item = await resolve_item(session, self.guild_id, str(self.item))
            if item is None:
                await interaction.response.send_message("Предмет не найден.", ephemeral=True)
                return
            method = str(self.method).strip().casefold().replace(" ", "_")
            method = re.sub(r"[^a-z0-9_]+", "_", method).strip("_")
            result = await session.execute(delete(FoxholeRecipeOverride).where(
                FoxholeRecipeOverride.guild_id == self.guild_id,
                FoxholeRecipeOverride.item_id == item.id,
                FoxholeRecipeOverride.production_method == method,
            ))
            await AuditService.log(
                session, guild_id=self.guild_id, user_id=interaction.user.id,
                user_name=str(interaction.user), action="CALCULATOR_OVERRIDE_DELETED",
                target_type="FOXHOLE_ITEM", target_id=item.id,
                details={"method": method, "deleted": result.rowcount},
            )
            await session.commit()
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Override удалён", f"Удалено записей: {result.rowcount}"), ephemeral=True
        )
