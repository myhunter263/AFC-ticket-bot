from __future__ import annotations

import datetime
import io
import json
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.command_sync import sync_commands_to_guild
from database.session import async_session_maker
from config import config
from services.ticket_service import TicketService
from services.audit_service import AuditService
from services.foxhole_api import FoxholeAPIError
from services.item_catalog_service import ItemCatalogService
from services.item_sync_service import ItemSyncService
from services.item_resolver import ItemResolver
from services.unknown_query_service import UnknownQueryService
from services.recipe_audit_service import RecipeAuditService
from ui.views.admin_panel import AdminPanelView
from utils.embeds import EmbedBuilder
from utils.permissions import PermissionChecker

logger = logging.getLogger(__name__)


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.foxhole_auto_sync.change_interval(
            hours=max(1, config.FOXHOLEHQ_SYNC_INTERVAL_HOURS)
        )
        self.foxhole_auto_sync.start()

    async def cog_unload(self) -> None:
        self.foxhole_auto_sync.cancel()

    @tasks.loop(hours=24)
    async def foxhole_auto_sync(self) -> None:
        for guild in self.bot.guilds:
            try:
                async with async_session_maker() as session:
                    status = await ItemSyncService.status(session, guild.id)
                    last_success = status["last_success_at"]
                    due_after = datetime.timedelta(
                        hours=max(1, config.FOXHOLEHQ_SYNC_INTERVAL_HOURS)
                    )
                    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
                    if (
                        last_success
                        and now - last_success < due_after
                        and status["resource_count"] >= 4
                    ):
                        await ItemSyncService.ensure_localizations(session, guild.id)
                        await ItemCatalogService.ensure_seed(session, guild.id)
                        await session.commit()
                        continue
                    result = await ItemSyncService.sync(session, guild.id)
                    await ItemCatalogService.ensure_seed(session, guild.id)
                    await session.commit()
                if not result.success:
                    logger.warning(
                        "Automatic FoxholeHQ sync failed for guild %d: %s",
                        guild.id,
                        result.error,
                    )
            except Exception:
                logger.exception("Automatic FoxholeHQ sync crashed for guild %d", guild.id)

    @foxhole_auto_sync.before_loop
    async def before_foxhole_auto_sync(self) -> None:
        await self.bot.wait_until_ready()

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
                value=f"Автор: <@{t.author_id}> | Канал: <#{t.ticket_channel_id}>",
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
        synced = await sync_commands_to_guild(self.bot, interaction.guild)
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
                result = await ItemCatalogService.sync(session, interaction.guild_id)
                if not result.success:
                    await session.commit()
                    raise FoxholeAPIError(result.error or "Неизвестная ошибка синхронизации")
                await ItemCatalogService.ensure_seed(session, interaction.guild_id)
                await AuditService.log(
                    session,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    user_name=str(interaction.user),
                    action="refresh_foxhole_catalog",
                    details={
                        "items": result.item_count,
                        "recipes": result.recipe_count,
                        "changed": result.changed,
                        "version": result.source_version,
                    },
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
            embed=EmbedBuilder.success(
                "Каталог FoxholeHQ обновлён",
                (
                    f"Версия: **{result.source_version or 'не указана'}**\n"
                    f"Предметов: **{result.item_count}**, рецептов: **{result.recipe_count}**\n"
                    f"Новых: **{result.created}**, переименовано: **{result.renamed}**, "
                    f"деактивировано: **{result.deactivated}**\n"
                    f"Без русского названия: **{result.untranslated}**\n"
                    f"Изменения dataset: **{'да' if result.changed else 'нет'}**"
                ),
            ),
            ephemeral=True,
        )

    @app_commands.command(name="afc-foxhole-status", description="[AFC] Состояние данных FoxholeHQ")
    @app_commands.guild_only()
    async def foxhole_status(self, interaction: discord.Interaction) -> None:
        if not await self._require_admin(interaction):
            return
        async with async_session_maker() as session:
            status = await ItemSyncService.status(session, interaction.guild_id)
            await session.commit()
        success_at = status["last_success_at"].strftime("%d.%m.%Y %H:%M UTC") if status["last_success_at"] else "ещё не было"
        error = status["last_error"] or "нет"
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Foxhole data status",
                description=(
                    f"Источник: **FoxholeHQ**\n"
                    f"Версия: **{status['source_version'] or 'не загружена'}**\n"
                    f"Последняя успешная синхронизация: **{success_at}**\n"
                    f"Предметов: **{status['item_count']}**\n"
                    f"Рецептов: **{status['recipe_count']}**\n"
                    f"Без русского названия: **{status['untranslated']}**\n"
                    f"Последняя ошибка: {error[:800]}"
                ),
                color=0x5865F2,
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="afc-foxhole-untranslated",
        description="[AFC] Показать предметы FoxholeHQ без русского названия",
    )
    @app_commands.guild_only()
    async def foxhole_untranslated(self, interaction: discord.Interaction) -> None:
        if not await self._require_admin(interaction):
            return
        from database.models import FoxholeItem, FoxholeItemLocalization
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        async with async_session_maker() as session:
            rows = list((await session.execute(
                select(FoxholeItemLocalization)
                .join(FoxholeItem)
                .where(
                    FoxholeItemLocalization.guild_id == interaction.guild_id,
                    FoxholeItem.is_active == True,
                    FoxholeItemLocalization.translation_status == "missing",
                )
                .options(selectinload(FoxholeItemLocalization.item))
                .order_by(FoxholeItem.api_name)
                .limit(25)
            )).scalars().all())
        description = "\n".join(
            f"`{row.item_id}` {row.item.api_name}" for row in rows
        ) or "Все активные предметы переведены."
        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"Без русского названия: {len(rows)} показано",
                description=description[:4000],
                color=0xFEE75C,
            ),
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

    @app_commands.command(name="afc-item-debug", description="[AFC] Диагностика распознавания предмета")
    @app_commands.describe(query="Проверяемый текст или жаргонизм")
    @app_commands.guild_only()
    async def item_debug(self, interaction: discord.Interaction, query: str) -> None:
        if not await self._require_admin(interaction):
            return
        async with async_session_maker() as session:
            catalog = await ItemCatalogService.get_catalog(session, interaction.guild_id)
            await session.commit()
        result = ItemResolver(catalog).debug(query)
        matched = result["matched"]
        candidate_lines = [
            f"{candidate.item.ru_name} (`{candidate.item.api_name}`) — "
            f"{candidate.confidence}% via `{candidate.matched_by}`"
            for candidate in result["candidates"]
        ]
        description = (
            f"**Input:** `{query}`\n"
            f"**Normalized:** `{result['normalized']}`\n"
            f"**Matched item:** {matched.item.api_name if matched else 'не выбран'}\n"
            f"**RU:** {matched.item.ru_name if matched else '—'}\n"
            f"**Confidence:** {matched.confidence if matched else '—'}%\n"
            f"**Source:** `{result['source']}`\n\n"
            f"**Candidates:**\n" + ("\n".join(candidate_lines) or "нет")
        )
        await interaction.response.send_message(
            embed=discord.Embed(title="Resolver debug", description=description[:4096], color=0x5865F2),
            ephemeral=True,
        )

    @app_commands.command(name="afc-unknown-aliases", description="[AFC] Частые неизвестные названия")
    @app_commands.guild_only()
    async def unknown_aliases(self, interaction: discord.Interaction) -> None:
        if not await self._require_admin(interaction):
            return
        async with async_session_maker() as session:
            rows = await UnknownQueryService.top(session, interaction.guild_id)
        description = "\n".join(
            f"`{row.raw_query}` — **{row.count}** раз" for row in rows
        ) or "Неизвестных запросов пока нет."
        await interaction.response.send_message(
            embed=discord.Embed(title="Неизвестные названия", description=description[:4096], color=0xFEE75C),
            ephemeral=True,
        )

    @app_commands.command(name="foxhole_dictionary_status", description="[AFC] Покрытие русского словаря Foxhole")
    @app_commands.guild_only()
    async def dictionary_status(self, interaction: discord.Interaction) -> None:
        if not await self._require_admin(interaction):
            return
        async with async_session_maker() as session:
            await ItemCatalogService.ensure_seed(session, interaction.guild_id)
            status = await ItemCatalogService.dictionary_status(session, interaction.guild_id)
            await session.commit()
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Русский словарь Foxhole",
                description=(
                    f"Всего предметов FoxholeHQ: **{status['total']}**\n"
                    f"Имеют русское название: **{status['translated']}**\n"
                    f"Имеют aliases: **{status['with_aliases']}**\n"
                    f"Без русского словаря: **{status['without_dictionary']}**"
                ),
                color=0x5865F2,
            ),
            ephemeral=True,
        )

    @app_commands.command(name="item_price_debug", description="[AFC] Проверить цену предмета Foxhole")
    @app_commands.describe(query="Русское, английское название или алиас")
    @app_commands.guild_only()
    async def item_price_debug(self, interaction: discord.Interaction, query: str) -> None:
        if not await self._require_admin(interaction):
            return
        async with async_session_maker() as session:
            catalog = await ItemCatalogService.get_catalog(session, interaction.guild_id)
            await session.commit()
        resolved = ItemResolver(catalog).resolve(query)
        from services.foxhole_types import ResolvedItem
        if not isinstance(resolved, ResolvedItem):
            await interaction.response.send_message(
                embed=EmbedBuilder.warning("Предмет не определён", query), ephemeral=True
            )
            return
        data = RecipeAuditService.item_debug(resolved.item)
        standard = data["standard"] or {}
        mpf = data["mpf"] or {}
        breakdown_lines = []
        labels = config.FOXHOLE_RESOURCE_LABELS
        for resource, rows in data["mpf_breakdown"].items():
            label = labels.get(resource, resource.upper())
            breakdown_lines.extend(
                f"#{row['position']} {row['percent']}% → {row['cost']} {label}"
                for row in rows
            )
        breakdown_text = "\n".join(breakdown_lines) or "недоступно"
        description = (
            f"**Item:** {data['name']} (`{data['api_name']}`)\n"
            f"**FoxholeHQ ID:** `{data['api_id']}`\n\n"
            f"**Production group:** `{resolved.item.production_group.upper()}`\n"
            f"**Order unit:** `{'EACH' if resolved.item.is_equipment else 'CRATE'}`\n\n"
            f"**{resolved.item.factory_site or 'Factory'}:** `{standard.get('materials') or resolved.item.factory_cost}`\n"
            f"Output: `{standard.get('output_quantity', 1)} {standard.get('output_unit', 'unknown')}`\n\n"
            f"**MPF:** `{mpf.get('materials') or 'недоступно'}`\n"
            f"Output: `{mpf.get('output_quantity', '—')} {mpf.get('output_unit', '')}`\n"
            f"Vehicles per crate: `{(mpf.get('raw_data') or {}).get('vehicles_per_crate') or '—'}`\n"
            f"Max queue: `{data['mpf_queues']}`\n"
            f"Max queue cost: `{data['mpf_max_queue_cost'] or '—'}`\n\n"
            f"**Расчёт MPF по позициям:**\n{breakdown_text}\n\n"
            f"**Source:** `{data['source']} {data['source_version'] or ''}`\n"
            f"**Local override:** `{'да' if data['overrides'] else 'нет'}`\n"
            f"**Validation:** `{data['validation']}`"
        )
        await interaction.response.send_message(
            embed=discord.Embed(title="Проверка цены", description=description[:4096], color=0x5865F2),
            ephemeral=True,
        )

    @app_commands.command(name="foxhole_price_audit", description="[AFC] Массовый аудит цен FoxholeHQ")
    @app_commands.guild_only()
    async def foxhole_price_audit(self, interaction: discord.Interaction) -> None:
        if not await self._require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        async with async_session_maker() as session:
            report = await RecipeAuditService.audit_database(session, interaction.guild_id)
        details = (report.errors + report.warnings)[:20]
        description = (
            f"Проверено предметов: **{report.item_count}**\n"
            f"Рецептов: **{report.recipe_count}**\n"
            f"Ошибок: **{len(report.errors)}**\n"
            f"Предупреждений: **{len(report.warnings)}**\n"
            f"Garage anomalies: **{report.garage_anomalies}**\n"
            f"Factory anomalies: **{report.factory_anomalies}**\n"
            f"MPF anomalies: **{report.mpf_anomalies}**\n"
            f"Missing recipes: **{report.missing_recipes}**\n"
            f"Manual overrides: **{len(report.manual_overrides)}**"
        )
        if details:
            description += "\n\n" + "\n".join(f"• {line}" for line in details)
        await interaction.followup.send(
            embed=discord.Embed(title="Аудит цен FoxholeHQ", description=description[:4096], color=0x57F287 if not report.errors else 0xED4245),
            ephemeral=True,
        )

    @app_commands.command(name="afc-dictionary-export", description="[AFC] Экспорт словаря Foxhole в JSON")
    @app_commands.guild_only()
    async def dictionary_export(self, interaction: discord.Interaction) -> None:
        if not await self._require_admin(interaction):
            return
        async with async_session_maker() as session:
            entries = await ItemCatalogService.export_dictionary(
                session, interaction.guild_id
            )
        payload = json.dumps(entries, ensure_ascii=False, indent=2).encode("utf-8")
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Словарь экспортирован", f"Предметов: **{len(entries)}**"),
            file=discord.File(io.BytesIO(payload), filename="foxhole_ru_aliases.json"),
            ephemeral=True,
        )

    @app_commands.command(name="afc-dictionary-import", description="[AFC] Импорт словаря Foxhole из JSON")
    @app_commands.describe(file="JSON-файл, полученный экспортом словаря")
    @app_commands.guild_only()
    async def dictionary_import(
        self, interaction: discord.Interaction, file: discord.Attachment
    ) -> None:
        if not await self._require_admin(interaction):
            return
        if file.size > 2_000_000:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Файл слишком большой", "Максимальный размер: 2 МБ."),
                ephemeral=True,
            )
            return
        try:
            entries = json.loads((await file.read()).decode("utf-8-sig"))
            if not isinstance(entries, list):
                raise ValueError
        except (UnicodeError, json.JSONDecodeError, ValueError):
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Неверный JSON", "Ожидается массив записей словаря."),
                ephemeral=True,
            )
            return
        async with async_session_maker() as session:
            result = await ItemCatalogService.import_dictionary(
                session, interaction.guild_id, entries, interaction.user.id
            )
            await AuditService.log(
                session,
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action="import_foxhole_dictionary",
                details=result,
            )
            await session.commit()
        await interaction.response.send_message(
            embed=EmbedBuilder.success(
                "Словарь импортирован",
                f"Алиасов добавлено: **{result['added']}**\n"
                f"Названий обновлено: **{result['updated']}**\n"
                f"Неизвестных ID пропущено: **{result['skipped']}**",
            ),
            ephemeral=True,
        )

    @app_commands.command(name="afc-item-alias-add", description="[AFC] Добавить жаргонизм к предмету")
    @app_commands.describe(
        item_id="ID из /afc-item-search",
        alias="Новое русское название или жаргонизм",
        alias_type="slang, abbreviation, transliteration, typo, caliber или custom",
        priority="Приоритет 0-200; стандартное значение 100",
    )
    @app_commands.guild_only()
    async def item_alias_add(
        self,
        interaction: discord.Interaction,
        item_id: int,
        alias: str,
        alias_type: str = "custom",
        priority: app_commands.Range[int, 0, 200] = 100,
    ) -> None:
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
                await ItemCatalogService.add_alias(
                    session,
                    localization,
                    alias,
                    interaction.user.id,
                    alias_type=alias_type,
                    priority=priority,
                )
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
                details={"alias": alias, "alias_type": alias_type, "priority": priority},
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
            localization.translation_status = "translated"
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
        is_vehicle="Физически является транспортным средством",
        production_group="AUTO, ITEM или EQUIPMENT (единица заказа и MPF-очередь)",
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
        production_group: str | None = None,
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
            try:
                await ItemCatalogService.update_overrides(
                    session,
                    localization,
                    category=category.strip() if category else None,
                    is_vehicle=is_vehicle,
                    production_group=production_group,
                    factory_site=factory_site.strip() if factory_site else None,
                    factory_cost=parsed_cost,
                    crate_size=crate_size,
                    vehicle_crate_size=vehicle_crate_size,
                    mpf_available=mpf_available,
                    mpf_max_crates=mpf_max_crates,
                )
            except ValueError as exc:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Неверный производственный класс", str(exc)),
                    ephemeral=True,
                )
                return
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
                    "production_group": production_group,
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
                f"Ручные параметры **{item_name}** имеют приоритет над FoxholeHQ.",
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
