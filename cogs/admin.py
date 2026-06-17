from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from database.session import async_session_maker
from services.ticket_service import TicketService
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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
