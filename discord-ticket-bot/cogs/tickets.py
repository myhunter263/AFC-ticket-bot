from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from database.session import async_session_maker
from services.status_service import StatusService
from services.ticket_service import TicketService
from ui.views.ticket_view import TicketPanelButtonView, TicketView, _refresh_ticket_embed
from utils.embeds import EmbedBuilder
from utils.permissions import PermissionChecker
from utils.transcript import TranscriptGenerator

logger = logging.getLogger(__name__)


class TicketsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        await self._restore_persistent_views()

    async def _restore_persistent_views(self) -> None:
        async with async_session_maker() as session:
            from sqlalchemy import select
            from database.models import TicketPanel, Ticket

            result = await session.execute(
                select(TicketPanel).where(TicketPanel.is_active == True)
            )
            panels = result.scalars().all()
            for panel in panels:
                view = TicketPanelButtonView(panel.id, panel.button_label, panel.button_emoji)
                self.bot.add_view(view)

            result = await session.execute(
                select(Ticket).where(Ticket.is_closed == False)
            )
            tickets = result.scalars().all()
            for ticket in tickets:
                view = TicketView(ticket_id=ticket.id, guild_id=ticket.guild_id)
                self.bot.add_view(view)

        logger.info(
            "Restored %d panel views and %d ticket views.",
            len(panels),
            len(tickets),
        )

    @app_commands.command(name="add-user", description="Добавить пользователя в тикет")
    @app_commands.guild_only()
    async def add_user(self, interaction: discord.Interaction, member: discord.Member) -> None:
        async with async_session_maker() as session:
            ticket = await TicketService.get_by_channel(session, interaction.channel_id)
            if not ticket:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Эта команда доступна только внутри тикета."),
                    ephemeral=True,
                )
                return
            if not await PermissionChecker.is_staff(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
                )
                return

        await interaction.channel.set_permissions(
            member,
            view_channel=True,
            send_messages=True,
            attach_files=True,
            embed_links=True,
        )
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Пользователь добавлен", f"{member.mention} добавлен в тикет."),
        )

    @app_commands.command(name="remove-user", description="Удалить пользователя из тикета")
    @app_commands.guild_only()
    async def remove_user(self, interaction: discord.Interaction, member: discord.Member) -> None:
        async with async_session_maker() as session:
            ticket = await TicketService.get_by_channel(session, interaction.channel_id)
            if not ticket:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Эта команда доступна только внутри тикета."),
                    ephemeral=True,
                )
                return
            if not await PermissionChecker.is_staff(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
                )
                return
            if member.id == ticket.author_id:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нельзя", "Нельзя удалить автора тикета."),
                    ephemeral=True,
                )
                return

        await interaction.channel.set_permissions(member, overwrite=None)
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Пользователь удалён", f"{member.mention} удалён из тикета.")
        )

    @app_commands.command(name="transcript", description="Создать транскрипт текущего тикета")
    @app_commands.guild_only()
    async def transcript(self, interaction: discord.Interaction) -> None:
        async with async_session_maker() as session:
            ticket = await TicketService.get_by_channel(session, interaction.channel_id)
            if not ticket:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Эта команда доступна только внутри тикета."),
                    ephemeral=True,
                )
                return
            if not await PermissionChecker.is_staff(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
                )
                return
            responses = ticket.responses
            status_name = ticket.status.name if ticket.status else "Неизвестно"

        await interaction.response.defer(ephemeral=True)

        html_buf = await TranscriptGenerator.generate_html(
            ticket=ticket,
            channel=interaction.channel,
            guild=interaction.guild,
            responses=responses,
            status_name=status_name,
        )
        txt_buf = await TranscriptGenerator.generate_txt(
            ticket=ticket,
            channel=interaction.channel,
            guild=interaction.guild,
            responses=responses,
            status_name=status_name,
        )

        await interaction.followup.send(
            embed=EmbedBuilder.success("Транскрипт", f"Заявка #{ticket.number:04d}"),
            files=[
                discord.File(html_buf, filename=f"ticket-{ticket.number:04d}.html"),
                discord.File(txt_buf, filename=f"ticket-{ticket.number:04d}.txt"),
            ],
            ephemeral=True,
        )

    @app_commands.command(name="ticket-info", description="Показать информацию о текущем тикете")
    @app_commands.guild_only()
    async def ticket_info(self, interaction: discord.Interaction) -> None:
        async with async_session_maker() as session:
            ticket = await TicketService.get_by_channel(session, interaction.channel_id)
            if not ticket:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Эта команда доступна только внутри тикета."),
                    ephemeral=True,
                )
                return
            responses = ticket.responses
            status = ticket.status
            status_name = status.name if status else "Неизвестно"
            status_color = status.color if status else 0x5865F2
            status_emoji = status.emoji or "" if status else ""
            assignee_id = ticket.assignee_id

        guild = interaction.guild
        author = guild.get_member(ticket.author_id)
        assignee = guild.get_member(assignee_id) if assignee_id else None

        embed = EmbedBuilder.ticket_card(
            ticket=ticket,
            author=author or interaction.user,
            assignee=assignee,
            status_name=status_name,
            status_color=status_color,
            status_emoji=status_emoji,
            responses=responses,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="close", description="Закрыть текущий тикет")
    @app_commands.guild_only()
    async def close_ticket_cmd(self, interaction: discord.Interaction) -> None:
        async with async_session_maker() as session:
            ticket = await TicketService.get_by_channel(session, interaction.channel_id)
            if not ticket:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Эта команда доступна только внутри тикета."),
                    ephemeral=True,
                )
                return
            if not await PermissionChecker.can_manage_ticket(interaction, session, ticket):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
                )
                return
            if ticket.is_closed:
                await interaction.response.send_message(
                    embed=EmbedBuilder.warning("Уже закрыта", "Заявка уже закрыта."), ephemeral=True
                )
                return

        from ui.views.ticket_view import ConfirmCloseView
        from utils.embeds import EmbedBuilder as EB

        view = ConfirmCloseView(ticket.id, interaction.guild_id)
        await interaction.response.send_message(
            embed=EB.warning("Закрыть заявку?", "Подтвердите закрытие."),
            view=view,
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketsCog(bot))
