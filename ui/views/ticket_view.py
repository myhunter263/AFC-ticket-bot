from __future__ import annotations

import logging
from typing import Optional

import discord
from sqlalchemy import select

from config import config
from database.models import Guild, StaffRole, TicketStatus
from database.session import async_session_maker
from services.audit_service import AuditService
from services.points_service import PointsService
from services.status_service import StatusService
from services.ticket_service import TicketService
from services.item_catalog_service import ItemCatalogService
from services.order_preview_service import OrderPreviewService
from ui.modals.ticket_modal import TicketCreateModal
from ui.modals.report_modal import ReportModal
from utils.auto_delete import respond_and_delete, schedule_delete
from utils.embeds import EmbedBuilder
from utils.permissions import PermissionChecker
from utils.transcript import TranscriptGenerator

logger = logging.getLogger(__name__)


def _member_overwrite() -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        attach_files=True,
        embed_links=True,
        read_message_history=True,
    )


def _staff_overwrite() -> discord.PermissionOverwrite:
    overwrite = _member_overwrite()
    overwrite.manage_messages = True
    return overwrite


def _bot_overwrite() -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        attach_files=True,
        embed_links=True,
        read_message_history=True,
        manage_channels=True,
        manage_messages=True,
    )


async def _get_staff_roles(session, guild_id: int) -> list[StaffRole]:
    result = await session.execute(
        select(StaffRole).where(StaffRole.guild_id == guild_id)
    )
    return list(result.scalars().all())


async def _ensure_archive_category(
    session,
    guild: discord.Guild,
    staff_roles: list[StaffRole],
) -> discord.CategoryChannel:
    db_guild = await session.get(Guild, guild.id)
    archive = (
        guild.get_channel(db_guild.archive_category_id)
        if db_guild and db_guild.archive_category_id
        else None
    )
    overwrites: dict = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: _bot_overwrite(),
    }
    for staff_role in staff_roles:
        if staff_role.role_type != "admin":
            continue
        role = guild.get_role(staff_role.role_id)
        if role:
            overwrites[role] = _staff_overwrite()

    if isinstance(archive, discord.CategoryChannel):
        await archive.edit(
            overwrites=overwrites,
            reason="Sync AFC Ticket Bot archive permissions",
        )
    else:
        archive = await guild.create_category(
            "Архив тикетов",
            overwrites=overwrites,
            reason="AFC Ticket Bot archive category",
        )
        if db_guild:
            db_guild.archive_category_id = archive.id
            await session.flush()
    return archive


async def _archive_ticket_channel(session, ticket, channel: discord.TextChannel) -> None:
    guild = channel.guild
    staff_roles = await _get_staff_roles(session, guild.id)
    archive = await _ensure_archive_category(session, guild, staff_roles)

    if ticket.original_category_id is None:
        ticket.original_category_id = channel.category_id

    await channel.edit(
        category=archive,
        sync_permissions=True,
        reason="Ticket archived",
    )
    await session.flush()


async def _restore_ticket_channel(session, ticket, channel: discord.TextChannel) -> None:
    guild = channel.guild
    staff_roles = await _get_staff_roles(session, guild.id)
    category_id = ticket.original_category_id
    if category_id is None and ticket.panel:
        category_id = ticket.panel.category_id
    category = guild.get_channel(category_id) if category_id else None
    if not isinstance(category, discord.CategoryChannel):
        category = None

    overwrites: dict = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: _bot_overwrite(),
    }

    author = guild.get_member(ticket.author_id)
    if author:
        overwrites[author] = _member_overwrite()

    for staff_role in staff_roles:
        if staff_role.panel_id is not None and staff_role.panel_id != ticket.panel_id:
            continue
        role = guild.get_role(staff_role.role_id)
        if role:
            overwrites[role] = _staff_overwrite()

    if ticket.panel:
        for role_id in ticket.panel.viewer_role_ids or []:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = _member_overwrite()

    for assignee in ticket.assignees:
        member = guild.get_member(assignee.user_id)
        if member:
            overwrites[member] = _member_overwrite()

    await channel.edit(
        category=category,
        overwrites=overwrites,
        sync_permissions=False,
        reason="Ticket reopened",
    )


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
            ping_role_ids = panel.ping_role_ids or []
            viewer_role_ids = panel.viewer_role_ids or []

        if form_fields:
            async def on_modal_submit(inter: discord.Interaction, responses: list[dict]) -> None:
                for response, metadata in zip(responses, form_fields):
                    response["field_type"] = metadata["field_type"]
                order_response = next(
                    (response for response in responses if response.get("field_type") == "foxhole_order"),
                    None,
                )
                if order_response:
                    await _show_order_preview(
                        inter, self.panel_id, form_id, responses, category_id,
                        ping_role_ids, viewer_role_ids, order_response["value"], panel_name,
                    )
                else:
                    await inter.response.defer(ephemeral=True)
                    await _finish_ticket_creation(
                        inter, self.panel_id, form_id, responses, category_id,
                        ping_role_ids, viewer_role_ids
                    )

            modal = TicketCreateModal(
                panel_name=panel_name,
                fields=form_fields,
                on_submit_callback=on_modal_submit,
            )
            await interaction.response.send_modal(modal)
        else:
            await interaction.response.defer(ephemeral=True)
            await _finish_ticket_creation(
                interaction, self.panel_id, None, [], category_id, ping_role_ids, viewer_role_ids
            )


async def _finish_ticket_creation(
    interaction: discord.Interaction,
    panel_id: int,
    form_id: Optional[int],
    responses: list[dict],
    category_id: Optional[int],
    ping_role_ids: list,
    viewer_role_ids: list,
    order_items: list[dict] | None = None,
) -> None:
    guild = interaction.guild
    user = interaction.user

    category = guild.get_channel(category_id) if category_id else None
    channel_name = f"ticket-{user.name.lower().replace(' ', '-')}"

    overwrites: dict = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: _member_overwrite(),
        guild.me: _bot_overwrite(),
    }

    async with async_session_maker() as session:
        staff_roles = await _get_staff_roles(session, guild.id)
        for sr in staff_roles:
            if sr.panel_id is not None and sr.panel_id != panel_id:
                continue
            role = guild.get_role(sr.role_id)
            if role:
                overwrites[role] = _staff_overwrite()

    # Viewer roles — can see and write, no manage rights
    for role_id in viewer_role_ids:
        role = guild.get_role(role_id)
        if role:
            overwrites[role] = _member_overwrite()

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
            original_category_id=category.id if category else None,
            author_id=user.id,
            status_id=default_status.id if default_status else None,
        )
        if responses:
            await TicketService.save_responses(session, ticket, responses)
        if order_items:
            await TicketService.save_order_items(session, ticket, order_items)

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
        assignees=[],
        status_name=status_name,
        status_color=status_color,
        status_emoji=status_emoji,
        responses=responses,
        order_items=order_items or [],
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

    # Ping roles configured for this panel
    if ping_role_ids:
        mentions = " ".join(f"<@&{rid}>" for rid in ping_role_ids)
        try:
            await channel.send(
                content=mentions,
                allowed_mentions=discord.AllowedMentions(roles=True),
            )
        except discord.HTTPException:
            pass

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


async def _show_order_preview(
    interaction: discord.Interaction,
    panel_id: int,
    form_id: Optional[int],
    responses: list[dict],
    category_id: Optional[int],
    ping_role_ids: list,
    viewer_role_ids: list,
    order_text: str,
    panel_name: str,
) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    async with async_session_maker() as session:
        catalog = await ItemCatalogService.get_catalog(session, interaction.guild_id)
        await session.commit()

    service = OrderPreviewService(catalog)
    order = service.parse(order_text)
    if not order.items and not order.unresolved:
        await interaction.edit_original_response(
            embed=EmbedBuilder.error(
                "Заказ не распознан",
                "Укажите каждую позицию с количеством, например: `15 ящиков аргенти`.",
            ),
            view=None,
        )
        return

    view = OrderPreviewView(
        author_id=interaction.user.id,
        panel_id=panel_id,
        form_id=form_id,
        responses=responses,
        category_id=category_id,
        ping_role_ids=ping_role_ids,
        viewer_role_ids=viewer_role_ids,
        panel_name=panel_name,
        service=service,
        order=order,
    )
    await interaction.edit_original_response(embed=view.make_embed(), view=view)


class OrderPreviewView(discord.ui.View):
    def __init__(
        self,
        *,
        author_id: int,
        panel_id: int,
        form_id: Optional[int],
        responses: list[dict],
        category_id: Optional[int],
        ping_role_ids: list,
        viewer_role_ids: list,
        panel_name: str,
        service: OrderPreviewService,
        order,
    ) -> None:
        super().__init__(timeout=300)
        self.author_id = author_id
        self.panel_id = panel_id
        self.form_id = form_id
        self.responses = responses
        self.category_id = category_id
        self.ping_role_ids = ping_role_ids
        self.viewer_role_ids = viewer_role_ids
        self.panel_name = panel_name
        self.service = service
        self.order = order
        self._rebuild_candidates()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            embed=EmbedBuilder.error("Нет доступа", "Это предпросмотр другого пользователя."),
            ephemeral=True,
        )
        return False

    def make_embed(self) -> discord.Embed:
        description = self.service.format_order(self.order)
        if any(item.resolved.requires_confirmation for item in self.order.items):
            description += "\n\n⚠️ Проверьте позиции с вероятным совпадением перед созданием."
        if self.order.unresolved:
            description += "\n\nВыберите вариант для каждой нераспознанной позиции."
        return discord.Embed(
            title="Предпросмотр заказа",
            description=description[:4096],
            color=config.COLOR_WARNING if self.order.requires_confirmation else config.COLOR_SUCCESS,
        )

    def _rebuild_candidates(self) -> None:
        for child in list(self.children):
            if isinstance(child, discord.ui.Select):
                self.remove_item(child)
        for index, unresolved in enumerate(self.order.unresolved[:3]):
            options = [
                discord.SelectOption(
                    label=candidate.item.ru_name[:100],
                    value=f"{index}:{candidate.item.id}",
                    description=f"{candidate.item.api_name[:70]} · {candidate.confidence}%",
                )
                for candidate in unresolved.result.candidates[:24]
                if candidate.item.id is not None
            ]
            if not options:
                options = [
                    discord.SelectOption(
                        label=item.ru_name[:100],
                        value=f"{index}:{item.id}",
                        description=item.api_name[:100],
                    )
                    for item in self.service.catalog[:24]
                    if item.id is not None
                ]
            select_menu = discord.ui.Select(
                placeholder=f"Выберите: {unresolved.line.query}"[:150],
                options=options,
                row=min(index, 2),
            )
            select_menu.callback = self._choose_candidate
            self.add_item(select_menu)
        self.create_order.disabled = bool(self.order.unresolved)

    async def _choose_candidate(self, interaction: discord.Interaction) -> None:
        index, item_id = map(int, interaction.data["values"][0].split(":"))
        self.service.choose_candidate(self.order, index, item_id)
        self._rebuild_candidates()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="Создать заказ", style=discord.ButtonStyle.success, row=3)
    async def create_order(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=self.make_embed(), view=self)
        await _finish_ticket_creation(
            interaction,
            self.panel_id,
            self.form_id,
            self.responses,
            self.category_id,
            self.ping_role_ids,
            self.viewer_role_ids,
            self.service.snapshots(self.order),
        )
        self.stop()

    @discord.ui.button(label="Изменить", style=discord.ButtonStyle.secondary, row=3)
    async def edit_order(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        modal = TicketCreateModal(
            panel_name=self.panel_name,
            fields=[{
                "id": response.get("field_id"),
                "label": response["field_label"],
                "placeholder": response["value"][:100],
                "default": response["value"],
                "field_type": response.get("field_type", "text"),
                "is_required": True,
                "max_length": (
                    4000 if response.get("field_type") == "foxhole_order" else 1024
                ),
            } for response in self.responses],
            on_submit_callback=self._edited,
        )
        await interaction.response.send_modal(modal)

    async def _edited(self, interaction: discord.Interaction, responses: list[dict]) -> None:
        for response, old_response in zip(responses, self.responses):
            response["field_type"] = old_response.get("field_type", "text")
        order_response = next(
            response for response in responses if response.get("field_type") == "foxhole_order"
        )
        await _show_order_preview(
            interaction, self.panel_id, self.form_id, responses, self.category_id,
            self.ping_role_ids, self.viewer_role_ids, order_response["value"], self.panel_name,
        )

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.danger, row=3)
    async def cancel_order(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(
            embed=EmbedBuilder.info("Создание отменено", "Заявка не была создана."),
            view=None,
        )


class TicketView(discord.ui.View):
    """Controls attached to the ticket embed message."""

    def __init__(self, ticket_id: int, guild_id: int) -> None:
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
        self.guild_id = guild_id

    @discord.ui.button(label="Взяться за тикет", style=discord.ButtonStyle.primary, emoji="🙋", row=0, custom_id="tv:claim")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            ticket = await TicketService.get_by_id(session, self.ticket_id)
            if not ticket:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Заявка не найдена."), ephemeral=True
                )
                return
            if ticket.is_closed:
                await interaction.response.send_message(
                    embed=EmbedBuilder.warning("Закрыта", "Заявка уже закрыта."), ephemeral=True
                )
                return
            if not await PermissionChecker.is_staff(
                interaction,
                session,
                ticket.panel_id,
            ):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error(
                        "Нет доступа",
                        "Взяться за заявку может только настроенный персонал этой панели.",
                    ),
                    ephemeral=True,
                )
                return

            _, was_already = await TicketService.claim(
                session, ticket, interaction.user.id, interaction.user.id
            )

            if was_already:
                await TicketService.unclaim(session, ticket, interaction.user.id)
                await AuditService.log(
                    session,
                    guild_id=self.guild_id,
                    user_id=interaction.user.id,
                    user_name=str(interaction.user),
                    action="unclaim_ticket",
                    target_type="ticket",
                    target_id=self.ticket_id,
                )
                await session.commit()

                await interaction.channel.set_permissions(
                    interaction.user,
                    overwrite=None,
                    reason="Ticket assignee removed",
                )
                await interaction.response.send_message(
                    embed=EmbedBuilder.info(
                        "Вы отказались от тикета",
                        f"{interaction.user.mention} больше не является исполнителем.",
                    ),
                )
                schedule_delete(interaction, delay=6.0)
            else:
                await AuditService.log(
                    session,
                    guild_id=self.guild_id,
                    user_id=interaction.user.id,
                    user_name=str(interaction.user),
                    action="claim_ticket",
                    target_type="ticket",
                    target_id=self.ticket_id,
                )
                await session.commit()

                await interaction.channel.set_permissions(
                    interaction.user,
                    overwrite=_member_overwrite(),
                    reason="Ticket assignee added",
                )
                await interaction.response.send_message(
                    embed=EmbedBuilder.success(
                        "Тикет взят",
                        f"{interaction.user.mention} взялся за заявку.",
                    ),
                )
                schedule_delete(interaction, delay=6.0)

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
                embed=EmbedBuilder.warning("Нет статусов", "Создайте статусы через /afc-admin."),
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
            embed=EmbedBuilder.info("Передача заявки", "Выберите сотрудника для передачи заявки:"),
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
            await _restore_ticket_channel(session, ticket, interaction.channel)
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

        await interaction.response.send_message(embed=EmbedBuilder.success("Заявка переоткрыта", "Заявка снова открыта."))
        schedule_delete(interaction, delay=6.0)
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

    @discord.ui.button(label="Отчёт", style=discord.ButtonStyle.secondary, emoji="📝", row=2, custom_id="tv:report")
    async def submit_report(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            ticket = await TicketService.get_by_id(session, self.ticket_id)
            if not ticket:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Заявка не найдена."), ephemeral=True
                )
                return
            if ticket.is_closed:
                await interaction.response.send_message(
                    embed=EmbedBuilder.warning("Закрыта", "Нельзя добавить отчёт к закрытой заявке."),
                    ephemeral=True,
                )
                return
            # Allow ticket author, assignees, and staff
            user_id = interaction.user.id
            is_assignee = any(a.user_id == user_id for a in ticket.assignees)
            is_author = ticket.author_id == user_id
            is_staff = await PermissionChecker.is_staff(interaction, session)

        if not (is_assignee or is_author or is_staff):
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "Нет доступа",
                    "Отчёт могут отправлять автор заявки, исполнители или персонал.",
                ),
                ephemeral=True,
            )
            return

        ticket_id = self.ticket_id

        async def _on_report(inter: discord.Interaction, content: str) -> None:
            async with async_session_maker() as sess:
                await TicketService.add_report(sess, ticket_id, inter.user.id, content)
                await AuditService.log(
                    sess,
                    guild_id=self.guild_id,
                    user_id=inter.user.id,
                    user_name=str(inter.user),
                    action="add_report",
                    target_type="ticket",
                    target_id=ticket_id,
                )
                await sess.commit()

            report_embed = discord.Embed(
                title="📝 Отчёт о выполнении",
                description=content,
                color=config.COLOR_SUCCESS,
            )
            report_embed.set_author(name=str(inter.user), icon_url=inter.user.display_avatar.url)
            report_embed.timestamp = __import__("datetime").datetime.utcnow()

            await inter.channel.send(embed=report_embed)
            await respond_and_delete(
                inter,
                EmbedBuilder.success("Отчёт добавлен", "Ваш отчёт опубликован в канале заявки."),
            )

        modal = ReportModal(on_submit=_on_report)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Начислить баллы", style=discord.ButtonStyle.secondary, emoji="⭐", row=2, custom_id="tv:award")
    async def award_points(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            ticket = await TicketService.get_by_id(session, self.ticket_id)
            if not ticket:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Заявка не найдена."), ephemeral=True
                )
                return
            if interaction.user.id != ticket.author_id:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error(
                        "Нет доступа",
                        "Через заявку баллы может начислять только её автор.",
                    ),
                    ephemeral=True,
                )
                return
            assignee_ids = [assignee.user_id for assignee in ticket.assignees]

        if not assignee_ids:
            await interaction.response.send_message(
                embed=EmbedBuilder.info(
                    "Нет исполнителей",
                    "Сначала сотрудник должен взяться за эту заявку.",
                ),
                ephemeral=True,
            )
            return

        view = TicketAwardView(
            self.ticket_id,
            self.guild_id,
            interaction.guild,
            assignee_ids,
        )
        await interaction.response.send_message(
            embed=EmbedBuilder.info(
                "Начислить баллы",
                "Выберите исполнителя и фиксированную награду:",
            ),
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="Удалить", style=discord.ButtonStyle.danger, emoji="🗑️", row=3, custom_id="tv:delete")
    async def delete_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            ticket = await TicketService.get_by_id(session, self.ticket_id)
            if not ticket:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Заявка не найдена."),
                    ephemeral=True,
                )
                return
            if not PermissionChecker.is_ticket_author_or_discord_admin(interaction, ticket):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error(
                        "Нет доступа",
                        "Удалить заявку может только её автор или администратор Discord-сервера.",
                    ),
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


class TicketAwardView(discord.ui.View):
    def __init__(
        self,
        ticket_id: int,
        guild_id: int,
        guild: discord.Guild,
        assignee_ids: list[int],
    ) -> None:
        super().__init__(timeout=60)
        self.ticket_id = ticket_id
        self.guild_id = guild_id
        self.selected_user_id: int | None = None

        options = []
        for user_id in assignee_ids[:25]:
            member = guild.get_member(user_id)
            display_name = member.display_name if member else f"ID {user_id}"
            options.append(
                discord.SelectOption(
                    label=display_name[:100],
                    value=str(user_id),
                    description="Исполнитель заявки",
                )
            )

        select = discord.ui.Select(
            placeholder="Выберите исполнителя...",
            options=options,
        )
        select.callback = self._select_assignee
        self.add_item(select)
        self._select = select

        award_50 = discord.ui.Button(
            label="+50",
            style=discord.ButtonStyle.success,
            emoji="⭐",
            disabled=True,
        )
        award_50.callback = self._award_50
        self.add_item(award_50)
        self._award_50_button = award_50

        award_100 = discord.ui.Button(
            label="+100",
            style=discord.ButtonStyle.success,
            emoji="⭐",
            disabled=True,
        )
        award_100.callback = self._award_100
        self.add_item(award_100)
        self._award_100_button = award_100

    async def _select_assignee(self, interaction: discord.Interaction) -> None:
        self.selected_user_id = int(self._select.values[0])
        self._award_50_button.disabled = False
        self._award_100_button.disabled = False
        await interaction.response.edit_message(view=self)

    async def _award_50(self, interaction: discord.Interaction) -> None:
        await self._award(interaction, 50)

    async def _award_100(self, interaction: discord.Interaction) -> None:
        await self._award(interaction, 100)

    async def _award(self, interaction: discord.Interaction, amount: int) -> None:
        user_id = self.selected_user_id
        if user_id is None:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Ошибка", "Сначала выберите исполнителя."),
                ephemeral=True,
            )
            return
        async with async_session_maker() as session:
            ticket = await TicketService.get_by_id(session, self.ticket_id)
            if not ticket or interaction.user.id != ticket.author_id:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа", "Начислять баллы может только автор этой заявки."),
                    ephemeral=True,
                )
                return
            if user_id not in {assignee.user_id for assignee in ticket.assignees}:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Этот пользователь больше не является исполнителем заявки."),
                    ephemeral=True,
                )
                return
            entry = await PointsService.award(session, self.guild_id, user_id, amount)
            await AuditService.log(
                session,
                guild_id=self.guild_id,
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action="award_points",
                target_type="user",
                target_id=user_id,
                details={"amount": amount, "ticket_id": self.ticket_id},
            )
            await session.commit()
            new_total = entry.points

        member = interaction.guild.get_member(user_id)
        mention = member.mention if member else f"<@{user_id}>"
        award_embed = discord.Embed(
            title="⭐ Баллы начислены",
            description=f"{mention} получил **+{amount} баллов**!\nВсего баллов: **{new_total}**",
            color=config.COLOR_SUCCESS,
        )
        award_embed.set_author(
            name=str(interaction.user),
            icon_url=interaction.user.display_avatar.url,
        )
        await interaction.channel.send(embed=award_embed)
        await respond_and_delete(
            interaction,
            EmbedBuilder.success(
                "Баллы начислены",
                f"{mention} получил **{amount}** баллов. Итого: **{new_total}**.",
            ),
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
            if not await PermissionChecker.is_staff(
                interaction,
                session,
                ticket.panel_id,
            ):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"),
                    ephemeral=True,
                )
                return
            old_name = ticket.status.name if ticket.status else "—"
            was_closed = ticket.is_closed
            await TicketService.update_status(session, ticket, new_status)
            if new_status.is_closed and not was_closed:
                await _archive_ticket_channel(session, ticket, interaction.channel)
            elif not new_status.is_closed and was_closed:
                await _restore_ticket_channel(session, ticket, interaction.channel)
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
        await respond_and_delete(
            interaction,
            EmbedBuilder.success("Статус изменён", f"Новый статус: **{new_status.name}**"),
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
            if ticket.is_closed:
                await interaction.response.send_message(
                    embed=EmbedBuilder.warning("Закрыта", "Нельзя передать закрытую заявку."),
                    ephemeral=True,
                )
                return
            if not await PermissionChecker.is_staff(
                interaction,
                session,
                ticket.panel_id,
            ):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"),
                    ephemeral=True,
                )
                return
            # Add as assignee
            await TicketService.claim(session, ticket, member.id, interaction.user.id)
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

        await interaction.channel.set_permissions(
            member,
            overwrite=_member_overwrite(),
            reason="Ticket transferred",
        )
        channel = interaction.channel
        await channel.send(
            embed=discord.Embed(
                description=f"🔄 Заявка передана: {member.mention}",
                color=config.COLOR_INFO,
            )
        )
        await respond_and_delete(
            interaction,
            EmbedBuilder.success("Передано", f"Заявка передана {member.mention}."),
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
            if not await PermissionChecker.can_manage_ticket(interaction, session, ticket):
                await interaction.followup.send(
                    embed=EmbedBuilder.error("Нет доступа"),
                    ephemeral=True,
                )
                return
            if ticket.is_closed:
                await interaction.followup.send(
                    embed=EmbedBuilder.warning("Уже закрыта", "Заявка уже закрыта."),
                    ephemeral=True,
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
            await _archive_ticket_channel(session, ticket, interaction.channel)
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
        async with async_session_maker() as session:
            ticket = await TicketService.get_by_id(session, self.ticket_id)
            if not ticket or not PermissionChecker.is_ticket_author_or_discord_admin(interaction, ticket):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error(
                        "Нет доступа",
                        "Удалить заявку может только её автор или администратор Discord-сервера.",
                    ),
                    ephemeral=True,
                )
                return

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
            responses = [
                {
                    "field_id": response.field_id,
                    "field_label": response.field_label,
                    "value": response.value,
                    "field_type": response.field_type or "text",
                }
                for response in ticket.responses
            ]
            status = ticket.status
            status_name = status.name if status else "Неизвестно"
            status_color = status.color if status else config.COLOR_PRIMARY
            status_emoji = status.emoji or "" if status else ""
            assignee_user_ids = [a.user_id for a in ticket.assignees]
            order_items = list(ticket.order_items)
            message_id = ticket.message_id

        channel = interaction.channel
        try:
            msg = await channel.fetch_message(message_id)
        except discord.NotFound:
            return

        guild = interaction.guild
        author = guild.get_member(ticket.author_id)
        assignees = [m for uid in assignee_user_ids if (m := guild.get_member(uid))]

        embed = EmbedBuilder.ticket_card(
            ticket=ticket,
            author=author or interaction.user,
            assignees=assignees,
            status_name=status_name,
            status_color=status_color,
            status_emoji=status_emoji,
            responses=responses,
            order_items=order_items,
        )
        view = TicketView(ticket_id=ticket_id, guild_id=interaction.guild_id)
        await msg.edit(embed=embed, view=view)
    except Exception as e:
        logger.warning("Failed to refresh ticket embed: %s", e)
