from __future__ import annotations

import discord

from database.session import async_session_maker
from services.audit_service import AuditService
from services.foxhole_api import FoxholeAPIError
from services.item_catalog_service import ItemCatalogService
from ui.modals.item_modal import ItemSearchModal, ItemValueModal
from utils.embeds import EmbedBuilder
from utils.permissions import PermissionChecker


class ItemCatalogView(discord.ui.View):
    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=300)
        self.guild_id = guild_id

    async def _allowed(self, interaction: discord.Interaction) -> bool:
        async with async_session_maker() as session:
            allowed = await PermissionChecker.is_bot_admin(interaction, session)
        if not allowed:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
            )
        return allowed

    @discord.ui.button(label="Найти предмет", style=discord.ButtonStyle.primary)
    async def search(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._allowed(interaction):
            return

        async def on_search(inter: discord.Interaction, query: str) -> None:
            await inter.response.defer(ephemeral=True)
            async with async_session_maker() as session:
                await ItemCatalogService.ensure_seed(session, self.guild_id)
                results = await ItemCatalogService.search(session, self.guild_id, query, 25)
                await session.commit()
            if not results:
                await inter.edit_original_response(
                    embed=EmbedBuilder.info("Ничего не найдено", f"Нет совпадений для **{query}**."),
                    view=None,
                )
                return
            await inter.edit_original_response(
                embed=discord.Embed(
                    title="Результаты поиска",
                    description="Выберите предмет для управления словарём.",
                    color=0x5865F2,
                ),
                view=ItemSearchResultsView(self.guild_id, results),
            )

        await interaction.response.send_modal(ItemSearchModal(on_search))

    @discord.ui.button(label="Обновить данные", style=discord.ButtonStyle.success)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._allowed(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            async with async_session_maker() as session:
                count = await ItemCatalogService.sync(session, self.guild_id)
                await ItemCatalogService.ensure_seed(session, self.guild_id)
                await AuditService.log(
                    session,
                    guild_id=self.guild_id,
                    user_id=interaction.user.id,
                    user_name=str(interaction.user),
                    action="refresh_foxhole_catalog",
                    details={"items": count},
                )
                await session.commit()
        except FoxholeAPIError as exc:
            await interaction.edit_original_response(
                embed=EmbedBuilder.warning(
                    "Каталог не обновлён",
                    f"{exc}\nИспользуется последний локальный кэш.",
                ),
                view=self,
            )
            return
        await interaction.edit_original_response(
            embed=EmbedBuilder.success("Каталог обновлён", f"Получено предметов: **{count}**."),
            view=self,
        )


class ItemSearchResultsView(discord.ui.View):
    def __init__(self, guild_id: int, results: list) -> None:
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.selected_item_id: int | None = None
        self.select = discord.ui.Select(
            placeholder="Выберите предмет...",
            options=[
                discord.SelectOption(
                    label=result.ru_name[:100],
                    value=str(result.item_id),
                    description=result.item.api_name[:100],
                )
                for result in results[:25]
            ],
        )
        self.select.callback = self._selected
        self.add_item(self.select)
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        async with async_session_maker() as session:
            allowed = await PermissionChecker.is_bot_admin(interaction, session)
        if not allowed:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
            )
        return allowed

    async def _selected(self, interaction: discord.Interaction) -> None:
        self.selected_item_id = int(self.select.values[0])
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = False
        await self._show(interaction)

    async def _get(self):
        async with async_session_maker() as session:
            return await ItemCatalogService.get_localization(
                session, self.guild_id, self.selected_item_id
            )

    async def _show(self, interaction: discord.Interaction) -> None:
        localization = await self._get()
        if localization is None:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Предмет не найден"), ephemeral=True
            )
            return
        aliases = ", ".join(alias.alias for alias in localization.aliases) or "нет"
        embed = discord.Embed(title=localization.ru_name, color=0x5865F2)
        embed.description = f"`{localization.item.api_name}`\n\n**Алиасы:** {aliases}"[:4096]
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Добавить алиас", style=discord.ButtonStyle.success, row=1)
    async def add_alias(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async def save(inter: discord.Interaction, value: str) -> None:
            async with async_session_maker() as session:
                localization = await ItemCatalogService.get_localization(
                    session, self.guild_id, self.selected_item_id
                )
                try:
                    await ItemCatalogService.add_alias(session, localization, value, inter.user.id)
                except ValueError as exc:
                    await inter.response.send_message(
                        embed=EmbedBuilder.warning("Не сохранено", str(exc)), ephemeral=True
                    )
                    return
                await AuditService.log(
                    session,
                    guild_id=self.guild_id,
                    user_id=inter.user.id,
                    user_name=str(inter.user),
                    action="add_foxhole_alias",
                    target_type="foxhole_item",
                    target_id=self.selected_item_id,
                    details={"alias": value},
                )
                await session.commit()
            await inter.response.send_message(
                embed=EmbedBuilder.success("Алиас добавлен", value), ephemeral=True
            )

        await interaction.response.send_modal(
            ItemValueModal("Добавить алиас", "Новый алиас", save)
        )

    @discord.ui.button(label="Удалить алиас", style=discord.ButtonStyle.danger, row=1)
    async def remove_alias(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async def remove(inter: discord.Interaction, value: str) -> None:
            async with async_session_maker() as session:
                localization = await ItemCatalogService.get_localization(
                    session, self.guild_id, self.selected_item_id
                )
                removed = await ItemCatalogService.remove_alias(session, localization, value)
                if removed:
                    await AuditService.log(
                        session,
                        guild_id=self.guild_id,
                        user_id=inter.user.id,
                        user_name=str(inter.user),
                        action="remove_foxhole_alias",
                        target_type="foxhole_item",
                        target_id=self.selected_item_id,
                        details={"alias": value},
                    )
                await session.commit()
            embed = (
                EmbedBuilder.success("Алиас удалён", value)
                if removed else EmbedBuilder.info("Алиас не найден", value)
            )
            await inter.response.send_message(embed=embed, ephemeral=True)

        await interaction.response.send_modal(
            ItemValueModal("Удалить алиас", "Точный алиас", remove)
        )

    @discord.ui.button(label="Русское название", style=discord.ButtonStyle.primary, row=1)
    async def rename(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        localization = await self._get()

        async def save(inter: discord.Interaction, value: str) -> None:
            if not value:
                await inter.response.send_message(
                    embed=EmbedBuilder.error("Пустое название"), ephemeral=True
                )
                return
            async with async_session_maker() as session:
                row = await ItemCatalogService.get_localization(
                    session, self.guild_id, self.selected_item_id
                )
                old_name = row.ru_name
                row.ru_name = value[:200]
                await AuditService.log(
                    session,
                    guild_id=self.guild_id,
                    user_id=inter.user.id,
                    user_name=str(inter.user),
                    action="rename_foxhole_item",
                    target_type="foxhole_item",
                    target_id=self.selected_item_id,
                    details={"from": old_name, "to": value},
                )
                await session.commit()
            await inter.response.send_message(
                embed=EmbedBuilder.success("Название изменено", value), ephemeral=True
            )

        await interaction.response.send_modal(
            ItemValueModal(
                "Русское название", "Отображаемое название", save,
                localization.ru_name if localization else "",
            )
        )
