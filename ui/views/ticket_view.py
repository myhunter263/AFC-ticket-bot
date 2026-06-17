from __future__ import annotations

import logging
from typing import Optional

import discord
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from config import config
from database.models import LogSettings, NotificationSettings, StaffRole, Ticket, TicketStatus
from database.session import async_session_maker
from services.audit_service import AuditService
from services.status_service import StatusService
from services.ticket_service import TicketService
from ui.modals.ticket_modal import TicketCreateModal
from utils.embeds import EmbedBuilder
from utils.permissions import PermissionChecker
from utils.transcript import TranscriptGenerator

logger = logging.getLogger(__name__)


class TicketPanelButtonView(discord.ui.View):
    """Persistent view attached to the panel message in a channel."""

    def __init__(self, panel_id: int, button_label: str, button_emoji: Optional[str]) -> None:
        super().__init__(timeout=None)
        self.panel_id = panel_id

        btn = discord.ui.Button(
            label=button_label,
            emoji=button_emoji or None,
            style=discord.ButtonStyle.primary,
            custom_id=f"panel_create_ticket:{panel_id}",
        )
        btn.callback = self._create_ticket_callback
        self.add_item(btn)

    async def _create_ticket_callback(self, interaction: discord.Interaction) -> None:
        async with async_session_maker() as session:
            panel = await TicketService.get_panel_by_id(session, self.panel_id)
            if not panel or not panel.is_active:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Панель недоступна", "Эта панель отключена."),
                    ephemeral=True,
                )
                return

            open_count = await TicketService.count_open_by_user(
                session, interaction.guild_id, interaction.user.id
            )
            if open_count >= config.MAX_TICKETS_PER_USER:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error(
                        "Лимит заявок",
                        f"У вас уже есть **{open_count}** открытых заявок. "
                        f"Максимум: {config.MAX_TICKETS_PER_USER}.",
                    ),
                    ephemeral=True,
                )
                return

            form_fields = []
            form_id = panel.form_id
            if form_id and panel.form:
                form_fields = [
                    {
                        "id": f.id,
                        "label": f.label,
                        "placeholder": f.placeholder,
                        "field_type": f.field_type,
                        "is_required": f.is_required,
                        "min_length": f.min_length,
                        "max_length": f.max_length,
                    }
                    for f in panel.form.fields
                    if f.is_active
                ]
            panel_name = panel.name
            category_id = panel.category_id

        if form_fields:
            async def on_modal_submit(inter: discord.Interaction, responses: list[dict]) -> None:
                await _finish_ticket_creation(inter, self.panel_id, form_id, responses, category_id)

            modal = TicketCreateModal(
                panel_name=panel_name,
                fields=form_fields,
                on_submit_callback=on_modal_submit,
            )
            await interaction.response.send_modal(modal)
        else:
            await interaction.response.defer(ephemeral=True)
            await _finish_ticket_creation(interaction, self.panel_id, None, [], category_id)


async def _finish_ticket_creation(
    interaction: discord.Interaction,
    panel_id: int,
    form_id: Optional[int],
    responses: list[dict],
    category_id: Optional[int],
) -> None:
    guild = interaction.guild
    user = interaction.user

    category = guild.get_channel(category_id) if category_id else None
    channel_name = f"ticket-{user.name.lower().replace(' ', '-')}"

    overwrites: dict = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, attach_files=True, embed_links=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True,
            manage_messages=True,
        ),
    }

    async with async_session_maker() as session:
        result = await session.execute(
            select(StaffRole).where(StaffRole.guild_id == guild.id)
        )
        staff_roles = result.scalars().all()
        for sr in staff_roles:
            role = guild.get_role(sr.role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, manage_messages=True
                )

    try:
        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            reason=f"Ticket created by {user}",
        )
    except discord.HTTPException as e:
        logger.error("Failed to create ticket channel: %s", e)
        embed = EmbedBuilder.error("Ошибка", "Не удалось создать канал для заявки.")
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    async with async_session_maker() as session:
        default_status = await StatusService.get_default(session, guild.id)
        ticket = await TicketService.create_ticket(
            session,
            guild_id=guild.id,
            panel_id=panel_id,
            form_id=form_id,
            channel_id=channel.id,
            author_id=user.id,
            status_id=default_status.id if default_status else None,
        )
        if responses:
            await TicketService.save_responses(session, ticket, responses)

        await AuditService.log(
            session,
            guild_id=guild.id,
            user_id=user.id,
            user_name=str(user),
            action="create_ticket",
            target_type="ticket",
            target_id=ticket.id,
        )

        log_settings = await TicketService.get_log_settings(session, guild.id)
        await session.commit()

        ticket_number = ticket.number
        ticket_id = ticket.id
        status_name = default_status.name if default_status else "Новая"
        status_color = default_status.color if default_status else config.COLOR_PRIMARY
        status_emoji = default_status.emoji or ""

    member = guild.get_member(user.id)
    embed = EmbedBuilder.ticket_card(
        ticket=type("T", (), {
            "number": ticket_number, "id": ticket_id,
            "created_at": __import__("datetime").datetime.utcnow(),
            "closed_at": None, "assignee_id": None,
        })(),
        author=member or user,
        assignee=None,
        status_name=status_name,
        status_color=status_color,
        status_emoji=status_emoji,
        responses=responses,
    )

    view = TicketView(ticket_id=ticket_id, guild_id=guild.id)
    ticket_msg = await channel.send(
        content=user.mention,
        embed=embed,
        view=view,
    )

    async with async_session_maker() as session:
        t = await TicketService.get_by_id(session, ticket_id)
        if t:
            t.message_id = ticket_msg.id
            await session.commit()

    await channel.send(
        embed=discord.Embed(
            description=f"Заявка **#{ticket_number:04d}** создана. Ожидайте ответа.",
            color=config.COLOR_INFO,
        )
    )

    notify_embed = EmbedBuilder.success(
        "Заявка создана",
        f"Ваша заявка **#{ticket_number:04d}** создана в {channel.mention}.",
    )
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=notify_embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=notify_embed, ephemeral=True)
    except discord.HTTPException:
        pass

    if log_settings and log_settings.channel_create:
        log_ch = guild.get_channel(log_settings.channel_create)
        if log_ch:
            log_embed = discord.Embed(
                title="🎫 Новая заявка",
                description=f"**#{ticket_number:04d}** создана пользователем {user.mention} в {channel.mention}",
                color=config.COLOR_PRIMARY,
            )
            try:
                await log_ch.send(embed=log_embed)
            except discord.HTTPException:
                pass


class TicketView(discord.ui.View):
    """Controls attached to the ticket embed message."""

    def __init__(self, ticket_id: int, guild_id: int) -> None:
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
        self.guild_id = guild_id

    @discord.ui.button(label="Назначить себя", style=discord.ButtonStyle.primary, emoji="👤", row=0, custom_id="tv:assign")
    async def assign_self(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            if not await PermissionChecker.is_staff(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа", "Только сотрудники могут назначать исполнителей."),
                    ephemeral=True,
                )
                return
            ticket = await TicketService.get_by_id(session, self.ticket_id)
            if not ticket:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Заявка не найдена."), ephemeral=True
                )
                return
            await TicketService.assign(session, ticket, interaction.user.id)
            await AuditService.log(
                session,
                guild_id=self.guild_id,
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action="assign_ticket",
                target_type="ticket",
                target_id=self.ticket_id,
            )
            await session.commit()

        embed = EmbedBuilder.success(
            "Назначено",
            f"{interaction.user.mention} назначен исполнителем заявки.",
        )
        await interaction.response.send_message(embed=embed)
        await _refresh_ticket_embed(interaction, self.ticket_id)

    @discord.ui.button(label="Сменить статус", style=discord.ButtonStyle.secondary, emoji="🏷️", row=0, custom_id="tv:status")
    async def change_status(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            if not await PermissionChecker.is_staff(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
                )
                return
            statuses = await StatusService.get_all(session, self.guild_id)

        if not statuses:
            await interaction.response.send_message(
                embed=EmbedBuilder.warning("Нет статусов", "Создайте статусы через /admin."),
                ephemeral=True,
            )
            return

        options = [
            discord.SelectOption(
                label=s.name[:100],
                value=str(s.id),
                emoji=s.emoji or None,
                description=f"#{s.color:06X}" + (" • Закрывает" if s.is_closed else ""),
            )
            for s in statuses[:25]
        ]

        view = StatusChangeView(self.ticket_id, self.guild_id, options)
        await interaction.response.send_message(
            embed=EmbedBuilder.info("Выберите статус", "Выберите новый статус для заявки:"),
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="Передать", style=discord.ButtonStyle.secondary, emoji="🔄", row=0, custom_id="tv:transfer")
    async def transfer(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            if not await PermissionChecker.is_staff(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
                )
                return

        view = TransferView(self.ticket_id, self.guild_id)
        await interaction.response.send_message(
            embed=EmbedBuilder.info("Передача заявки", "Упомяните сотрудника для передачи заявки:"),
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="Закрыть", style=discord.ButtonStyle.danger, emoji="🔒", row=1, custom_id="tv:close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            ticket = await TicketService.get_by_id(session, self.ticket_id)
            if not ticket:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Заявка не найдена."), ephemeral=True
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

        view = ConfirmCloseView(self.ticket_id, self.guild_id)
        await interaction.response.send_message(
            embed=EmbedBuilder.warning(
                "Закрыть заявку?",
                "Подтвердите закрытие. Будет создан транскрипт.",
            ),
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="Открыть заново", style=discord.ButtonStyle.success, emoji="🔓", row=1, custom_id="tv:reopen")
    async def reopen_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            if not await PermissionChecker.is_staff(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
                )
                return
            ticket = await TicketService.get_by_id(session, self.ticket_id)
            if not ticket or not ticket.is_closed:
                await interaction.response.send_message(
                    embed=EmbedBuilder.warning("Уже открыта", "Заявка уже открыта."), ephemeral=True
                )
                return
            default_status = await StatusService.get_default(session, self.guild_id)
            await TicketService.reopen(session, ticket, default_status)
            await AuditService.log(
                session,
                guild_id=self.guild_id,
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action="reopen_ticket",
                target_type="ticket",
                target_id=self.ticket_id,
            )
            await session.commit()

        channel = interaction.channel
        await channel.set_permissions(
            interaction.guild.default_role, view_channel=False
        )
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Заявка переоткрыта", "Заявка снова открыта.")
        )
        await _refresh_ticket_embed(interaction, self.ticket_id)

    @discord.ui.button(label="Экспорт", style=discord.ButtonStyle.secondary, emoji="📄", row=1, custom_id="tv:export")
    async def export_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            if not await PermissionChecker.is_staff(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
                )
                return
            ticket = await TicketService.get_by_id(session, self.ticket_id)
            if not ticket:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Заявка не найдена."), ephemeral=True
                )
                return
            status_name = ticket.status.name if ticket.status else "Неизвестно"
            responses = ticket.responses

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
            embed=EmbedBuilder.success("Транскрипт готов", f"Заявка #{ticket.number:04d}"),
            files=[
                discord.File(html_buf, filename=f"ticket-{ticket.number:04d}.html"),
                discord.File(txt_buf, filename=f"ticket-{ticket.number:04d}.txt"),
            ],
            ephemeral=True,
        )

    @discord.ui.button(label="Удалить", style=discord.ButtonStyle.danger, emoji="🗑️", row=2, custom_id="tv:delete")
    async def delete_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            if not await PermissionChecker.is_bot_admin(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа", "Только администраторы могут удалять заявки."),
                    ephemeral=True,
                )
                return

        view = ConfirmDeleteTicketView(self.ticket_id, self.guild_id)
        await interaction.response.send_message(
            embed=EmbedBuilder.warning(
                "Удалить заявку?",
                "Канал будет удалён навсегда. Это действие необратимо.",
            ),
            view=view,
            ephemeral=True,
        )


class StatusChangeView(discord.ui.View):
    def __init__(self, ticket_id: int, guild_id: int, options: list) -> None:
        super().__init__(timeout=60)
        self.ticket_id = ticket_id
        self.guild_id = guild_id

        select = discord.ui.Select(placeholder="Выберите статус...", options=options)
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        status_id = int(interaction.data["values"][0])
        async with async_session_maker() as session:
            ticket = await TicketService.get_by_id(session, self.ticket_id)
            new_status = await StatusService.get_by_id(session, status_id)
            if not ticket or not new_status:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Заявка или статус не найдены."), ephemeral=True
                )
                return
            old_name = ticket.status.name if ticket.status else "—"
            await TicketService.update_status(session, ticket, new_status)
            await AuditService.log(
                session,
                guild_id=self.guild_id,
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action="change_status",
                target_type="ticket",
                target_id=self.ticket_id,
                details={"from": old_name, "to": new_status.name},
            )
            await session.commit()

        channel = interaction.channel
        await channel.send(
            embed=discord.Embed(
                description=f"🏷️ Статус изменён: **{old_name}** → **{new_status.name}**",
                color=new_status.color,
            )
        )
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Статус изменён", f"Новый статус: **{new_status.name}**"),
            ephemeral=True,
        )
        await _refresh_ticket_embed(interaction, self.ticket_id)


class TransferView(discord.ui.View):
    def __init__(self, ticket_id: int, guild_id: int) -> None:
        super().__init__(timeout=60)
        self.ticket_id = ticket_id
        self.guild_id = guild_id

        user_select = discord.ui.UserSelect(placeholder="Выберите сотрудника...")
        user_select.callback = self._select_user
        self.add_item(user_select)
        self._user_select = user_select

    async def _select_user(self, interaction: discord.Interaction) -> None:
        member = self._user_select.values[0]
        async with async_session_maker() as session:
            ticket = await TicketService.get_by_id(session, self.ticket_id)
            if not ticket:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Заявка не найдена."), ephemeral=True
                )
                return
            await TicketService.assign(session, ticket, member.id)
            await AuditService.log(
                session,
                guild_id=self.guild_id,
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action="transfer_ticket",
                target_type="ticket",
                target_id=self.ticket_id,
                details={"to": str(member)},
            )
            await session.commit()

        channel = interaction.channel
        await channel.send(
            embed=discord.Embed(
                description=f"🔄 Заявка передана: {member.mention}",
                color=config.COLOR_INFO,
            )
        )
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Передано", f"Заявка передана {member.mention}."),
            ephemeral=True,
        )
        await _refresh_ticket_embed(interaction, self.ticket_id)


class ConfirmCloseView(discord.ui.View):
    def __init__(self, ticket_id: int, guild_id: int) -> None:
        super().__init__(timeout=60)
        self.ticket_id = ticket_id
        self.guild_id = guild_id

    @discord.ui.button(label="Подтвердить закрытие", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)

        async with async_session_maker() as session:
            ticket = await TicketService.get_by_id(session, self.ticket_id)
            if not ticket:
                await interaction.followup.send(
                    embed=EmbedBuilder.error("Ошибка", "Заявка не найдена."), ephemeral=True
                )
                return

            result = await session.execute(
                select(TicketStatus).where(
                    TicketStatus.guild_id == self.guild_id,
                    TicketStatus.is_closed == True,
                ).order_by(TicketStatus.order).limit(1)
            )
            closed_status = result.scalar_one_or_none()
            responses = ticket.responses
            status_name = closed_status.name if closed_status else "Закрыта"

            await TicketService.close(session, ticket, interaction.user.id, closed_status)
            await AuditService.log(
                session,
                guild_id=self.guild_id,
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action="close_ticket",
                target_type="ticket",
                target_id=self.ticket_id,
            )
            log_settings = await TicketService.get_log_settings(session, self.guild_id)
            ticket_number = ticket.number
            await session.commit()

        channel = interaction.channel
        html_buf = await TranscriptGenerator.generate_html(
            ticket=ticket,
            channel=channel,
            guild=interaction.guild,
            responses=responses,
            status_name=status_name,
        )

        if log_settings and log_settings.channel_close:
            log_ch = interaction.guild.get_channel(log_settings.channel_close)
            if log_ch:
                log_embed = discord.Embed(
                    title="🔒 Заявка закрыта",
                    description=(
                        f"**#{ticket_number:04d}** закрыта пользователем {interaction.user.mention}\n"
                        f"Канал: {channel.name}"
                    ),
                    color=config.COLOR_WARNING,
                )
                try:
                    await log_ch.send(
                        embed=log_embed,
                        file=discord.File(html_buf, filename=f"ticket-{ticket_number:04d}.html"),
                    )
                except discord.HTTPException:
                    pass

        await interaction.followup.send(
            embed=EmbedBuilder.success("Заявка закрыта", "Транскрипт сохранён."),
            ephemeral=True,
        )

        close_embed = discord.Embed(
            description=f"🔒 Заявка **#{ticket_number:04d}** закрыта {interaction.user.mention}",
            color=config.COLOR_WARNING,
        )
        await channel.send(embed=close_embed)
        await _refresh_ticket_embed(interaction, self.ticket_id)

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=EmbedBuilder.info("Отменено", "Закрытие отменено."), view=None
        )


class ConfirmDeleteTicketView(discord.ui.View):
    def __init__(self, ticket_id: int, guild_id: int) -> None:
        super().__init__(timeout=60)
        self.ticket_id = ticket_id
        self.guild_id = guild_id

    @discord.ui.button(label="Удалить канал", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        try:
            await channel.delete(reason=f"Ticket deleted by {interaction.user}")
        except discord.HTTPException as e:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Ошибка", f"Не удалось удалить канал: {e}"), ephemeral=True
            )

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=EmbedBuilder.info("Отменено", "Удаление отменено."), view=None
        )


async def _refresh_ticket_embed(interaction: discord.Interaction, ticket_id: int) -> None:
    try:
        async with async_session_maker() as session:
            ticket = await TicketService.get_by_id(session, ticket_id)
            if not ticket or not ticket.message_id:
                return
            responses = ticket.responses
            status = ticket.status
            status_name = status.name if status else "Неизвестно"
            status_color = status.color if status else config.COLOR_PRIMARY
            status_emoji = status.emoji or "" if status else ""
            assignee_id = ticket.assignee_id
            message_id = ticket.message_id

        channel = interaction.channel
        try:
            msg = await channel.fetch_message(message_id)
        except discord.NotFound:
            return

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
        view = TicketView(ticket_id=ticket_id, guild_id=interaction.guild_id)
        await msg.edit(embed=embed, view=view)
    except Exception as e:
        logger.warning("Failed to refresh ticket embed: %s", e)
