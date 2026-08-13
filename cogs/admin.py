from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from database.session import async_session_maker
from services.ticket_service import TicketService
from services.audit_service import AuditService
from services.foxhole_api import FoxholeAPIError
from services.item_catalog_service import ItemCatalogService
from ui.views.admin_panel import AdminPanelView
from utils.embeds import EmbedBuilder
from utils.permissions import PermissionChecker

logger = logging.getLogger(__name__)


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="afc-admin", description="[AFC] Открыть панель управления ботом")
    @app_commands.guild_only()
    async def admin(self, interaction: discord.Interaction) -> None:
        async with async_session_maker() as session:
            is_admin = await PermissionChecker.is_bot_admin(interaction, session)

        if not is_admin:
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "Нет доступа",
                    "Только администраторы сервера или пользователи с ролью администратора могут открывать панель управления.",
                ),
                ephemeral=True,
            )
            return

        async with async_session_maker() as session:
            await TicketService.get_or_create_guild(session, interaction.guild)
            await session.commit()

        embed = EmbedBuilder.admin_panel_main()
        view = AdminPanelView(guild_id=interaction.guild_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="afc-tickets", description="[AFC] Показать список открытых заявок")
    @app_commands.guild_only()
    async def tickets_list(self, interaction: discord.Interaction) -> None:
        async with async_session_maker() as session:
            is_staff = await PermissionChecker.is_staff(interaction, session)
            if not is_staff:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа", "Только сотрудники могут просматривать список заявок."),
                    ephemeral=True,
                )
                return
            tickets = await TicketService.list_open(session, interaction.guild_id, limit=25)

        if not tickets:
            await interaction.response.send_message(
                embed=EmbedBuilder.info("Заявки", "Открытых заявок нет."),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"📊 Открытые заявки ({len(tickets)})",
            color=0x5865F2,
        )
        for t in tickets:
            status_str = t.status.name if t.status else "—"
            embed.add_field(
                name=f"#{t.number:04d} — {status_str}",
                value=f"Автор: <@{t.author_id}> | Канал: <#{t.channel_id}>",
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="afc-sync", description="[AFC] Синхронизировать slash-команды (только для владельца)")
    @app_commands.guild_only()
    async def sync_commands(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Нет доступа", "Только владелец сервера может синхронизировать команды."),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        synced = await self.bot.tree.sync(guild=interaction.guild)
        await interaction.followup.send(
            embed=EmbedBuilder.success("Команды синхронизированы", f"Синхронизировано {len(synced)} команд."),
            ephemeral=True,
        )

    async def _require_admin(self, interaction: discord.Interaction) -> bool:
        async with async_session_maker() as session:
            allowed = await PermissionChecker.is_bot_admin(interaction, session)
        if not allowed:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Нет доступа", "Команда доступна только администраторам бота."),
                ephemeral=True,
            )
        return allowed

    @app_commands.command(name="afc-items-refresh", description="[AFC] Обновить каталог предметов Foxhole")
    @app_commands.guild_only()
    async def refresh_items(self, interaction: discord.Interaction) -> None:
        if not await self._require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            async with async_session_maker() as session:
                count = await ItemCatalogService.sync(session, interaction.guild_id)
                await ItemCatalogService.ensure_seed(session, interaction.guild_id)
                await AuditService.log(
                    session,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    user_name=str(interaction.user),
                    action="refresh_foxhole_catalog",
                    details={"items": count},
                )
                await session.commit()
        except FoxholeAPIError as exc:
            await interaction.followup.send(
                embed=EmbedBuilder.warning(
                    "Каталог не обновлён",
                    f"{exc}\nБот продолжает использовать локальный кэш PostgreSQL.",
                ),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            embed=EmbedBuilder.success("Каталог обновлён", f"Синхронизировано предметов: **{count}**."),
            ephemeral=True,
        )

    @app_commands.command(name="afc-item-search", description="[AFC] Найти предмет и посмотреть его алиасы")
    @app_commands.describe(query="Русское, английское название или алиас")
    @app_commands.guild_only()
    async def item_search(self, interaction: discord.Interaction, query: str) -> None:
        if not await self._require_admin(interaction):
            return
        async with async_session_maker() as session:
            await ItemCatalogService.ensure_seed(session, interaction.guild_id)
            results = await ItemCatalogService.search(session, interaction.guild_id, query)
            await session.commit()
        if not results:
            await interaction.response.send_message(
                embed=EmbedBuilder.info("Ничего не найдено", f"По запросу **{query}** совпадений нет."),
                ephemeral=True,
            )
            return
        embed = discord.Embed(title="Каталог Foxhole", color=0x5865F2)
        for localization in results[:10]:
            aliases = ", ".join(alias.alias for alias in localization.aliases) or "нет"
            embed.add_field(
                name=f"[{localization.item_id}] {localization.ru_name}",
                value=f"`{localization.item.api_name}`\nАлиасы: {aliases}"[:1024],
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="afc-item-alias-add", description="[AFC] Добавить жаргонизм к предмету")
    @app_commands.describe(item_id="ID из /afc-item-search", alias="Новое русское название или жаргонизм")
    @app_commands.guild_only()
    async def item_alias_add(self, interaction: discord.Interaction, item_id: int, alias: str) -> None:
        if not await self._require_admin(interaction):
            return
        async with async_session_maker() as session:
            localization = await ItemCatalogService.get_localization(session, interaction.guild_id, item_id)
            if not localization:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Предмет не найден", "Сначала найдите ID через `/afc-item-search`."),
                    ephemeral=True,
                )
                return
            try:
                await ItemCatalogService.add_alias(session, localization, alias, interaction.user.id)
            except ValueError as exc:
                await interaction.response.send_message(
                    embed=EmbedBuilder.warning("Алиас не добавлен", str(exc)), ephemeral=True
                )
                return
            await AuditService.log(
                session,
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action="add_foxhole_alias",
                target_type="foxhole_item",
                target_id=item_id,
                details={"alias": alias},
            )
            await session.commit()
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Алиас добавлен", f"**{alias}** → **{localization.ru_name}**"),
            ephemeral=True,
        )

    @app_commands.command(name="afc-item-alias-remove", description="[AFC] Удалить алиас предмета")
    @app_commands.describe(item_id="ID из /afc-item-search", alias="Удаляемый алиас")
    @app_commands.guild_only()
    async def item_alias_remove(self, interaction: discord.Interaction, item_id: int, alias: str) -> None:
        if not await self._require_admin(interaction):
            return
        async with async_session_maker() as session:
            localization = await ItemCatalogService.get_localization(session, interaction.guild_id, item_id)
            removed = localization and await ItemCatalogService.remove_alias(session, localization, alias)
            if not removed:
                await interaction.response.send_message(
                    embed=EmbedBuilder.info("Алиас не найден", f"У предмета нет алиаса **{alias}**."),
                    ephemeral=True,
                )
                return
            await AuditService.log(
                session,
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action="remove_foxhole_alias",
                target_type="foxhole_item",
                target_id=item_id,
                details={"alias": alias},
            )
            await session.commit()
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Алиас удалён", f"Алиас **{alias}** удалён."), ephemeral=True
        )

    @app_commands.command(name="afc-item-rename", description="[AFC] Изменить русское название предмета")
    @app_commands.describe(item_id="ID из /afc-item-search", ru_name="Новое отображаемое название")
    @app_commands.guild_only()
    async def item_rename(self, interaction: discord.Interaction, item_id: int, ru_name: str) -> None:
        if not await self._require_admin(interaction):
            return
        ru_name = ru_name.strip()
        if not ru_name:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Пустое название"), ephemeral=True
            )
            return
        async with async_session_maker() as session:
            localization = await ItemCatalogService.get_localization(session, interaction.guild_id, item_id)
            if not localization:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Предмет не найден"), ephemeral=True
                )
                return
            old_name = localization.ru_name
            localization.ru_name = ru_name[:200]
            await AuditService.log(
                session,
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action="rename_foxhole_item",
                target_type="foxhole_item",
                target_id=item_id,
                details={"from": old_name, "to": ru_name},
            )
            await session.commit()
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Название изменено", f"**{old_name}** → **{ru_name}**"),
            ephemeral=True,
        )

    @app_commands.command(name="afc-item-override", description="[AFC] Переопределить производство предмета")
    @app_commands.describe(
        item_id="ID из /afc-item-search",
        category="Категория предмета",
        is_vehicle="Техника заказывается поштучно",
        factory_site="Factory, Garage или другое здание",
        factory_cost="Ресурсы: bmat=100,rmat=20",
        crate_size="Количество предметов в обычном ящике",
        vehicle_crate_size="Количество машин в одном MPF-ящике",
        mpf_available="Доступен ли предмет на MPF",
        mpf_max_crates="Максимум ящиков в MPF-партии",
    )
    @app_commands.guild_only()
    async def item_override(
        self,
        interaction: discord.Interaction,
        item_id: int,
        category: str | None = None,
        is_vehicle: bool | None = None,
        factory_site: str | None = None,
        factory_cost: str | None = None,
        crate_size: app_commands.Range[int, 1, 10000] | None = None,
        vehicle_crate_size: app_commands.Range[int, 1, 10] | None = None,
        mpf_available: bool | None = None,
        mpf_max_crates: app_commands.Range[int, 3, 9] | None = None,
    ) -> None:
        if not await self._require_admin(interaction):
            return
        parsed_cost = None
        if factory_cost is not None:
            parsed_cost = {}
            try:
                for part in factory_cost.split(","):
                    resource, amount = part.split("=", 1)
                    resource = resource.strip().casefold()
                    amount_value = int(amount.strip())
                    if not resource or amount_value < 0:
                        raise ValueError
                    if amount_value:
                        parsed_cost[resource] = amount_value
            except ValueError:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error(
                        "Неверная цена",
                        "Используйте формат `bmat=100,rmat=20`.",
                    ),
                    ephemeral=True,
                )
                return

        async with async_session_maker() as session:
            localization = await ItemCatalogService.get_localization(
                session, interaction.guild_id, item_id
            )
            if localization is None:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Предмет не найден"), ephemeral=True
                )
                return
            await ItemCatalogService.update_overrides(
                session,
                localization,
                category=category.strip() if category else None,
                is_vehicle=is_vehicle,
                factory_site=factory_site.strip() if factory_site else None,
                factory_cost=parsed_cost,
                crate_size=crate_size,
                vehicle_crate_size=vehicle_crate_size,
                mpf_available=mpf_available,
                mpf_max_crates=mpf_max_crates,
            )
            await AuditService.log(
                session,
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action="override_foxhole_item",
                target_type="foxhole_item",
                target_id=item_id,
                details={
                    "category": category,
                    "is_vehicle": is_vehicle,
                    "factory_site": factory_site,
                    "factory_cost": parsed_cost,
                    "crate_size": crate_size,
                    "vehicle_crate_size": vehicle_crate_size,
                    "mpf_available": mpf_available,
                    "mpf_max_crates": mpf_max_crates,
                },
            )
            await session.commit()
            item_name = localization.ru_name
        await interaction.response.send_message(
            embed=EmbedBuilder.success(
                "Параметры сохранены",
                f"Ручные параметры **{item_name}** имеют приоритет над API.",
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
