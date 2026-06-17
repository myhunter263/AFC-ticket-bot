from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from database.session import async_session_maker
from services.status_service import StatusService
from services.ticket_service import TicketService
from utils.embeds import EmbedBuilder

logger = logging.getLogger(__name__)


class SetupCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="setup", description="Первоначальная настройка бота на сервере")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def setup_bot(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        async with async_session_maker() as session:
            guild_obj = await TicketService.get_or_create_guild(session, interaction.guild)
            await StatusService.ensure_defaults(session, interaction.guild_id)
            await session.commit()

        synced = await self.bot.tree.sync(guild=interaction.guild)

        embed = discord.Embed(
            title="✅ Бот настроен",
            description=(
                "Бот успешно инициализирован на вашем сервере!\n\n"
                f"**Синхронизировано команд:** {len(synced)}\n"
                "**Созданы статусы по умолчанию:** Новая, В работе, Ожидание клиента, Завершена, Отменена\n\n"
                "Откройте панель управления командой `/admin` для настройки панелей тикетов."
            ),
            color=0x57F287,
        )
        embed.add_field(
            name="Доступные команды",
            value=(
                "`/admin` — панель управления\n"
                "`/tickets` — список открытых заявок\n"
                "`/close` — закрыть тикет\n"
                "`/transcript` — экспорт тикета\n"
                "`/ticket-info` — информация о тикете\n"
                "`/add-user` — добавить пользователя\n"
                "`/remove-user` — удалить пользователя\n"
            ),
            inline=False,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="bot-info", description="Информация о боте")
    @app_commands.guild_only()
    async def bot_info(self, interaction: discord.Interaction) -> None:
        async with async_session_maker() as session:
            tickets = await TicketService.list_open(session, interaction.guild_id, limit=1000)
            statuses = await StatusService.get_all(session, interaction.guild_id)

        embed = discord.Embed(
            title="ℹ️ Ticket Bot",
            description="Discord бот для управления заявками и тикетами.",
            color=0x5865F2,
        )
        embed.add_field(name="Серверов", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="Открытых заявок", value=str(len(tickets)), inline=True)
        embed.add_field(name="Статусов", value=str(len(statuses)), inline=True)
        embed.add_field(name="Задержка", value=f"{round(self.bot.latency * 1000)}ms", inline=True)
        embed.set_footer(text=f"discord.py {discord.__version__} | Python 3.11")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupCog(bot))
