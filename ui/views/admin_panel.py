from __future__ import annotations

import discord
from sqlalchemy import select

from config import config
from database.models import LogSettings, NotificationSettings, StaffRole
from database.session import async_session_maker
from services.audit_service import AuditService
from services.form_service import FormService
from services.status_service import StatusService
from services.ticket_service import TicketService
from ui.modals.panel_modal import PanelCreateModal, PanelEditModal
from ui.views.form_builder import FormListView
from ui.views.status_manager import StatusListView
from utils.embeds import EmbedBuilder
from utils.permissions import PermissionChecker


class AdminPanelView(discord.ui.View):
    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=300)
        self.guild_id = guild_id

    @discord.ui.button(label="Панели тикетов", style=discord.ButtonStyle.primary, emoji="🎫", row=0)
    async def manage_panels(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            if not await PermissionChecker.is_bot_admin(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
                )
                return
            panels = await TicketService.get_all_panels(session, self.guild_id)

        embed = discord.Embed(title="🎫 Панели тикетов", color=config.COLOR_PRIMARY)
        embed.description = f"Всего панелей: **{len(panels)}**"
        for p in panels[:10]:
            status = "✅" if p.is_active else "🔴"
            embed.add_field(
                name=f"{status} [{p.id}] {p.name}",
                value=f"Канал: <#{p.channel_id}>",
                inline=False,
            )

        view = PanelManageView(self.guild_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Формы", style=discord.ButtonStyle.primary, emoji="📋", row=0)
    async def manage_forms(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            if not await PermissionChecker.is_bot_admin(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
                )
                return

        embed = discord.Embed(title="📋 Конструктор форм", color=config.COLOR_PRIMARY)
        embed.description = "Создавайте и редактируйте формы для сбора данных при создании тикетов."
        view = FormListView(self.guild_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Статусы", style=discord.ButtonStyle.primary, emoji="🏷️", row=0)
    async def manage_statuses(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            if not await PermissionChecker.is_bot_admin(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
                )
                return
            statuses = await StatusService.get_all(session, self.guild_id)

        embed = discord.Embed(title="🏷️ Управление статусами", color=config.COLOR_PRIMARY)
        embed.description = f"Настроено статусов: **{len(statuses)}**"
        view = StatusListView(self.guild_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Роли", style=discord.ButtonStyle.secondary, emoji="👥", row=1)
    async def manage_roles(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            if not await PermissionChecker.is_bot_admin(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
                )
                return
            result = await session.execute(
                select(StaffRole).where(StaffRole.guild_id == self.guild_id)
            )
            roles = result.scalars().all()

        embed = discord.Embed(title="👥 Роли персонала", color=config.COLOR_PRIMARY)
        if roles:
            for r in roles:
                panel_info = f" (Панель #{r.panel_id})" if r.panel_id else " (Глобально)"
                embed.add_field(
                    name=f"<@&{r.role_id}>",
                    value=f"Тип: `{r.role_type}`{panel_info}",
                    inline=False,
                )
        else:
            embed.description = "Роли персонала не настроены."

        view = RoleManageView(self.guild_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Уведомления", style=discord.ButtonStyle.secondary, emoji="🔔", row=1)
    async def manage_notifications(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            if not await PermissionChecker.is_bot_admin(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
                )
                return
            settings = await TicketService.get_or_create_notification_settings(session, self.guild_id)
            await session.commit()
            s = settings

        embed = discord.Embed(title="🔔 Настройки уведомлений", color=config.COLOR_PRIMARY)
        embed.add_field(name="Новый тикет", value="✅" if s.notify_new_ticket else "🔴", inline=True)
        embed.add_field(name="Смена статуса", value="✅" if s.notify_status_change else "🔴", inline=True)
        embed.add_field(name="Назначение", value="✅" if s.notify_assignment else "🔴", inline=True)
        embed.add_field(name="Закрытие", value="✅" if s.notify_close else "🔴", inline=True)
        embed.add_field(name="DM при закрытии", value="✅" if s.dm_author_on_close else "🔴", inline=True)

        view = NotificationSettingsView(self.guild_id, s)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Каналы логов", style=discord.ButtonStyle.secondary, emoji="📝", row=1)
    async def manage_logs(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            if not await PermissionChecker.is_bot_admin(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
                )
                return
            log_settings = await TicketService.get_or_create_log_settings(session, self.guild_id)
            await session.commit()
            s = log_settings

        def ch_str(ch_id):
            return f"<#{ch_id}>" if ch_id else "Не задан"

        embed = discord.Embed(title="📝 Каналы логов", color=config.COLOR_PRIMARY)
        embed.add_field(name="Создание тикетов", value=ch_str(s.channel_create), inline=True)
        embed.add_field(name="Закрытие тикетов", value=ch_str(s.channel_close), inline=True)
        embed.add_field(name="Ошибки", value=ch_str(s.channel_error), inline=True)
        embed.add_field(name="Действия администраторов", value=ch_str(s.channel_admin), inline=True)

        view = LogSettingsView(self.guild_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Аудит", style=discord.ButtonStyle.secondary, emoji="🔍", row=2)
    async def view_audit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            if not await PermissionChecker.is_bot_admin(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
                )
                return
            logs = await AuditService.get_recent(session, self.guild_id, limit=15)

        embed = EmbedBuilder.audit_log_embed(logs)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Резервные копии", style=discord.ButtonStyle.secondary, emoji="💾", row=2)
    async def manage_backups(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            if not await PermissionChecker.is_bot_admin(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
                )
                return

        view = BackupView(self.guild_id)
        embed = discord.Embed(
            title="💾 Резервные копии",
            description=(
                "Управление резервными копиями данных.\n\n"
                "**Создать бэкап** — сохраняет текущее состояние БД.\n"
                "**Скачать бэкап** — выгружает последний дамп в файл."
            ),
            color=config.COLOR_PRIMARY,
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Открытые заявки", style=discord.ButtonStyle.primary, emoji="📊", row=2)
    async def view_open_tickets(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            if not await PermissionChecker.is_staff(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
                )
                return
            tickets = await TicketService.list_open(session, self.guild_id, limit=20)

        if not tickets:
            await interaction.response.send_message(
                embed=EmbedBuilder.info("Нет открытых заявок", "Все заявки закрыты."),
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="📊 Открытые заявки", color=config.COLOR_PRIMARY)
        for t in tickets:
            status_name = t.status.name if t.status else "—"
            assignee = f"<@{t.assignee_id}>" if t.assignee_id else "Не назначен"
            embed.add_field(
                name=f"#{t.number:04d}",
                value=f"Автор: <@{t.author_id}>\nСтатус: {status_name}\nИсполнитель: {assignee}\nКанал: <#{t.channel_id}>",
                inline=True,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)


class PanelManageView(discord.ui.View):
    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=300)
        self.guild_id = guild_id

    @discord.ui.button(label="Создать панель", style=discord.ButtonStyle.success, emoji="➕", row=0)
    async def create_panel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async def on_submit(inter: discord.Interaction, **kwargs) -> None:
            view = PanelSetupView(self.guild_id, **kwargs)
            embed = discord.Embed(
                title="⚙️ Настройка панели",
                description=(
                    f"**Название:** {kwargs['name']}\n"
                    "Выберите канал и форму для панели:"
                ),
                color=config.COLOR_PRIMARY,
            )
            await inter.response.send_message(embed=embed, view=view, ephemeral=True)

        modal = PanelCreateModal(on_submit)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Редактировать панель", style=discord.ButtonStyle.primary, emoji="✏️", row=0)
    async def edit_panel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            panels = await TicketService.get_all_panels(session, self.guild_id)

        if not panels:
            await interaction.response.send_message(
                embed=EmbedBuilder.info("Нет панелей", "Сначала создайте панель."), ephemeral=True
            )
            return

        options = [
            discord.SelectOption(
                label=p.name[:100],
                value=str(p.id),
                description=f"ID: {p.id} | {'✅ Активна' if p.is_active else '🔴 Отключена'}",
            )
            for p in panels[:25]
        ]

        view = PanelSelectEditView(self.guild_id, options)
        await interaction.response.send_message(
            embed=EmbedBuilder.info("Выберите панель", "Выберите панель для редактирования:"),
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="Удалить панель", style=discord.ButtonStyle.danger, emoji="🗑️", row=0)
    async def delete_panel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            panels = await TicketService.get_all_panels(session, self.guild_id)

        if not panels:
            await interaction.response.send_message(
                embed=EmbedBuilder.info("Нет панелей", "Сначала создайте панель."), ephemeral=True
            )
            return

        options = [
            discord.SelectOption(label=p.name[:100], value=str(p.id), description=f"ID: {p.id}")
            for p in panels[:25]
        ]

        view = PanelSelectDeleteView(self.guild_id, options)
        await interaction.response.send_message(
            embed=EmbedBuilder.warning("Выберите панель для удаления", ""),
            view=view,
            ephemeral=True,
        )


class PanelSetupView(discord.ui.View):
    def __init__(self, guild_id: int, name: str, description, button_label: str, button_emoji, color: int) -> None:
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.name = name
        self.description = description
        self.button_label = button_label
        self.button_emoji = button_emoji
        self.color = color
        self.selected_channel_id: int | None = None
        self.selected_form_id: int | None = None
        self.selected_category_id: int | None = None

        ch_select = discord.ui.ChannelSelect(
            placeholder="Выберите канал для панели...",
            channel_types=[discord.ChannelType.text],
            row=0,
        )
        ch_select.callback = self._select_channel
        self.add_item(ch_select)
        self._ch_select = ch_select

        cat_select = discord.ui.ChannelSelect(
            placeholder="Выберите категорию для тикетов (необязательно)...",
            channel_types=[discord.ChannelType.category],
            min_values=0,
            max_values=1,
            row=1,
        )
        cat_select.callback = self._select_category
        self.add_item(cat_select)
        self._cat_select = cat_select

    async def _select_channel(self, interaction: discord.Interaction) -> None:
        self.selected_channel_id = self._ch_select.values[0].id
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Канал выбран", f"Выбран канал: <#{self.selected_channel_id}>"),
            ephemeral=True,
        )

    async def _select_category(self, interaction: discord.Interaction) -> None:
        if self._cat_select.values:
            self.selected_category_id = self._cat_select.values[0].id
            await interaction.response.send_message(
                embed=EmbedBuilder.success("Категория выбрана", f"Тикеты будут создаваться в <#{self.selected_category_id}>."),
                ephemeral=True,
            )
        else:
            self.selected_category_id = None
            await interaction.response.send_message(
                embed=EmbedBuilder.info("Категория не выбрана", "Тикеты будут создаваться без категории."),
                ephemeral=True,
            )

    @discord.ui.button(label="Выбрать форму", style=discord.ButtonStyle.secondary, emoji="📋", row=2)
    async def pick_form(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            forms = await FormService.get_all(session, self.guild_id)

        if not forms:
            await interaction.response.send_message(
                embed=EmbedBuilder.info("Нет форм", "Формы не созданы. Создайте форму в разделе «Формы»."),
                ephemeral=True,
            )
            return

        options = [discord.SelectOption(label="Без формы", value="0", description="Создать тикет без заполнения формы")]
        options += [
            discord.SelectOption(
                label=f.name[:100],
                value=str(f.id),
                description=f"Полей: {len([x for x in f.fields if x.is_active])}",
            )
            for f in forms[:24]
        ]

        view = FormPickView(self, options)
        await interaction.response.send_message(
            embed=EmbedBuilder.info("Выберите форму", ""),
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="Опубликовать панель", style=discord.ButtonStyle.success, emoji="🚀", row=2)
    async def publish_panel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not self.selected_channel_id:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Ошибка", "Сначала выберите канал для панели."),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        channel = interaction.guild.get_channel(self.selected_channel_id)
        if not channel:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Ошибка", "Канал не найден."), ephemeral=True
            )
            return

        async with async_session_maker() as session:
            panel = await TicketService.create_panel(
                session,
                guild_id=self.guild_id,
                channel_id=self.selected_channel_id,
                name=self.name,
                description=self.description,
                color=self.color,
                category_id=self.selected_category_id,
                form_id=self.selected_form_id,
                button_label=self.button_label,
                button_emoji=self.button_emoji,
                created_by=interaction.user.id,
            )
            await AuditService.log(
                session,
                guild_id=self.guild_id,
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action="create_panel",
                target_type="panel",
                target_id=panel.id,
                details={"name": self.name},
            )
            await session.commit()
            panel_id = panel.id

        from ui.views.ticket_view import TicketPanelButtonView

        embed = EmbedBuilder.panel_embed(self.name, self.description or "", self.color)
        btn_view = TicketPanelButtonView(panel_id, self.button_label, self.button_emoji)
        msg = await channel.send(embed=embed, view=btn_view)

        async with async_session_maker() as session:
            p = await TicketService.get_panel_by_id(session, panel_id)
            if p:
                p.message_id = msg.id
                await session.commit()

        await interaction.followup.send(
            embed=EmbedBuilder.success(
                "Панель опубликована",
                f"Панель **{self.name}** опубликована в {channel.mention}.",
            ),
            ephemeral=True,
        )


class FormPickView(discord.ui.View):
    def __init__(self, parent: PanelSetupView, options: list) -> None:
        super().__init__(timeout=60)
        self.parent = parent

        select = discord.ui.Select(placeholder="Выберите форму...", options=options)
        select.callback = self._callback
        self.add_item(select)

    async def _callback(self, interaction: discord.Interaction) -> None:
        val = int(interaction.data["values"][0])
        self.parent.selected_form_id = val if val != 0 else None
        label = "без формы" if val == 0 else f"форма ID={val}"
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Форма выбрана", f"Выбрана: {label}"), ephemeral=True
        )


class PanelSelectEditView(discord.ui.View):
    def __init__(self, guild_id: int, options: list) -> None:
        super().__init__(timeout=60)
        self.guild_id = guild_id

        select = discord.ui.Select(placeholder="Выберите панель...", options=options)
        select.callback = self._callback
        self.add_item(select)

    async def _callback(self, interaction: discord.Interaction) -> None:
        panel_id = int(interaction.data["values"][0])

        async with async_session_maker() as session:
            panel = await TicketService.get_panel_by_id(session, panel_id)
            if not panel:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Панель не найдена."), ephemeral=True
                )
                return

        async def on_submit(inter: discord.Interaction, **kwargs) -> None:
            async with async_session_maker() as session:
                p = await TicketService.get_panel_by_id(session, panel_id)
                if p:
                    await TicketService.update_panel(session, p, **kwargs)
                    await AuditService.log(
                        session,
                        guild_id=self.guild_id,
                        user_id=inter.user.id,
                        user_name=str(inter.user),
                        action="update_panel",
                        target_type="panel",
                        target_id=panel_id,
                    )
                    await session.commit()

                    if p.message_id and p.channel_id:
                        channel = inter.guild.get_channel(p.channel_id)
                        if channel:
                            try:
                                msg = await channel.fetch_message(p.message_id)
                                embed = EmbedBuilder.panel_embed(p.name, p.description or "", p.color)
                                from ui.views.ticket_view import TicketPanelButtonView
                                btn_view = TicketPanelButtonView(panel_id, p.button_label, p.button_emoji)
                                await msg.edit(embed=embed, view=btn_view)
                            except discord.HTTPException:
                                pass

            await inter.response.send_message(
                embed=EmbedBuilder.success("Панель обновлена"), ephemeral=True
            )

        modal = PanelEditModal(
            on_submit,
            current_name=panel.name,
            current_description=panel.description,
            current_button_label=panel.button_label,
            current_button_emoji=panel.button_emoji,
            current_color=panel.color,
        )
        await interaction.response.send_modal(modal)


class PanelSelectDeleteView(discord.ui.View):
    def __init__(self, guild_id: int, options: list) -> None:
        super().__init__(timeout=60)
        self.guild_id = guild_id

        select = discord.ui.Select(placeholder="Выберите панель для удаления...", options=options)
        select.callback = self._callback
        self.add_item(select)

    async def _callback(self, interaction: discord.Interaction) -> None:
        panel_id = int(interaction.data["values"][0])

        async with async_session_maker() as session:
            panel = await TicketService.get_panel_by_id(session, panel_id)
            if not panel:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Панель не найдена."), ephemeral=True
                )
                return
            name = panel.name
            channel_id = panel.channel_id
            message_id = panel.message_id
            await TicketService.delete_panel(session, panel)
            await AuditService.log(
                session,
                guild_id=self.guild_id,
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action="delete_panel",
                target_type="panel",
                target_id=panel_id,
                details={"name": name},
            )
            await session.commit()

        if message_id and channel_id:
            channel = interaction.guild.get_channel(channel_id)
            if channel:
                try:
                    msg = await channel.fetch_message(message_id)
                    await msg.delete()
                except discord.HTTPException:
                    pass

        await interaction.response.send_message(
            embed=EmbedBuilder.success("Панель удалена", f"Панель **{name}** удалена."),
            ephemeral=True,
        )


class RoleManageView(discord.ui.View):
    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=180)
        self.guild_id = guild_id

        role_select = discord.ui.RoleSelect(
            placeholder="Выберите роль для добавления в персонал...",
            row=0,
        )
        role_select.callback = self._select_role
        self.add_item(role_select)
        self._role_select = role_select

    async def _select_role(self, interaction: discord.Interaction) -> None:
        role = self._role_select.values[0]
        view = RoleTypeSelectView(self.guild_id, role.id, role.name)
        await interaction.response.send_message(
            embed=EmbedBuilder.info(
                "Тип роли",
                f"Выберите тип для роли **{role.name}**:",
            ),
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="Удалить роль из персонала", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
    async def remove_role(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            result = await session.execute(
                select(StaffRole).where(StaffRole.guild_id == self.guild_id)
            )
            roles = result.scalars().all()

        if not roles:
            await interaction.response.send_message(
                embed=EmbedBuilder.info("Нет ролей", "Роли персонала не назначены."), ephemeral=True
            )
            return

        options = [
            discord.SelectOption(
                label=f"@{interaction.guild.get_role(r.role_id).name if interaction.guild.get_role(r.role_id) else r.role_id}",
                value=str(r.id),
                description=f"Тип: {r.role_type}",
            )
            for r in roles[:25]
        ]

        view = RoleDeleteView(self.guild_id, options)
        await interaction.response.send_message(
            embed=EmbedBuilder.warning("Выберите роль для удаления", ""),
            view=view,
            ephemeral=True,
        )


class RoleTypeSelectView(discord.ui.View):
    def __init__(self, guild_id: int, role_id: int, role_name: str) -> None:
        super().__init__(timeout=60)
        self.guild_id = guild_id
        self.role_id = role_id
        self.role_name = role_name

        options = [
            discord.SelectOption(label="Администратор", value="admin", description="Полный доступ к боту"),
            discord.SelectOption(label="Модератор", value="moderator", description="Управление тикетами"),
            discord.SelectOption(label="Оператор", value="operator", description="Ответы на тикеты"),
        ]
        select = discord.ui.Select(placeholder="Выберите тип...", options=options)
        select.callback = self._callback
        self.add_item(select)

    async def _callback(self, interaction: discord.Interaction) -> None:
        role_type = interaction.data["values"][0]

        async with async_session_maker() as session:
            existing = await session.execute(
                select(StaffRole).where(
                    StaffRole.guild_id == self.guild_id,
                    StaffRole.role_id == self.role_id,
                    StaffRole.panel_id.is_(None),
                )
            )
            if existing.scalar_one_or_none():
                await interaction.response.send_message(
                    embed=EmbedBuilder.warning("Уже добавлена", "Эта роль уже является персоналом."),
                    ephemeral=True,
                )
                return

            sr = StaffRole(
                guild_id=self.guild_id,
                role_id=self.role_id,
                role_type=role_type,
            )
            session.add(sr)
            await AuditService.log(
                session,
                guild_id=self.guild_id,
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action="add_staff_role",
                details={"role_id": self.role_id, "type": role_type},
            )
            await session.commit()

        await interaction.response.send_message(
            embed=EmbedBuilder.success(
                "Роль добавлена",
                f"**{self.role_name}** теперь является `{role_type}`.",
            ),
            ephemeral=True,
        )


class RoleDeleteView(discord.ui.View):
    def __init__(self, guild_id: int, options: list) -> None:
        super().__init__(timeout=60)
        self.guild_id = guild_id

        select = discord.ui.Select(placeholder="Выберите роль...", options=options)
        select.callback = self._callback
        self.add_item(select)

    async def _callback(self, interaction: discord.Interaction) -> None:
        sr_id = int(interaction.data["values"][0])
        async with async_session_maker() as session:
            result = await session.execute(select(StaffRole).where(StaffRole.id == sr_id))
            sr = result.scalar_one_or_none()
            if sr:
                await session.delete(sr)
                await AuditService.log(
                    session,
                    guild_id=self.guild_id,
                    user_id=interaction.user.id,
                    user_name=str(interaction.user),
                    action="remove_staff_role",
                    details={"role_id": sr.role_id},
                )
                await session.commit()

        await interaction.response.send_message(
            embed=EmbedBuilder.success("Роль удалена из персонала"), ephemeral=True
        )


class NotificationSettingsView(discord.ui.View):
    def __init__(self, guild_id: int, settings) -> None:
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.settings = settings

    async def _toggle(self, interaction: discord.Interaction, field: str, label: str) -> None:
        async with async_session_maker() as session:
            s = await TicketService.get_or_create_notification_settings(session, self.guild_id)
            current = getattr(s, field)
            setattr(s, field, not current)
            await session.commit()
            new_val = not current

        state = "включено" if new_val else "отключено"
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Обновлено", f"**{label}**: {state}"), ephemeral=True
        )

    @discord.ui.button(label="Новый тикет", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_new(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._toggle(interaction, "notify_new_ticket", "Уведомление о новом тикете")

    @discord.ui.button(label="Смена статуса", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_status(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._toggle(interaction, "notify_status_change", "Уведомление о смене статуса")

    @discord.ui.button(label="Назначение", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_assign(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._toggle(interaction, "notify_assignment", "Уведомление о назначении")

    @discord.ui.button(label="Закрытие", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._toggle(interaction, "notify_close", "Уведомление о закрытии")

    @discord.ui.button(label="DM при закрытии", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_dm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._toggle(interaction, "dm_author_on_close", "DM автору при закрытии")


class LogSettingsView(discord.ui.View):
    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=300)
        self.guild_id = guild_id

    async def _set_log_channel(self, interaction: discord.Interaction, field: str, label: str) -> None:
        view = LogChannelPickerView(self.guild_id, field, label)
        await interaction.response.send_message(
            embed=EmbedBuilder.info(f"Выберите канал для «{label}»", ""),
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="Канал создания", style=discord.ButtonStyle.primary, row=0)
    async def set_create(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._set_log_channel(interaction, "channel_create", "Создание тикетов")

    @discord.ui.button(label="Канал закрытия", style=discord.ButtonStyle.primary, row=0)
    async def set_close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._set_log_channel(interaction, "channel_close", "Закрытие тикетов")

    @discord.ui.button(label="Канал ошибок", style=discord.ButtonStyle.secondary, row=1)
    async def set_error(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._set_log_channel(interaction, "channel_error", "Ошибки")

    @discord.ui.button(label="Канал администраторов", style=discord.ButtonStyle.secondary, row=1)
    async def set_admin(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._set_log_channel(interaction, "channel_admin", "Действия администраторов")


class LogChannelPickerView(discord.ui.View):
    def __init__(self, guild_id: int, field: str, label: str) -> None:
        super().__init__(timeout=60)
        self.guild_id = guild_id
        self.field = field
        self.label = label

        ch_select = discord.ui.ChannelSelect(
            placeholder="Выберите канал...",
            channel_types=[discord.ChannelType.text],
        )
        ch_select.callback = self._pick_channel
        self.add_item(ch_select)
        self._ch_select = ch_select

    async def _pick_channel(self, interaction: discord.Interaction) -> None:
        channel = self._ch_select.values[0]
        async with async_session_maker() as session:
            settings = await TicketService.get_or_create_log_settings(session, self.guild_id)
            setattr(settings, self.field, channel.id)
            await session.commit()

        await interaction.response.send_message(
            embed=EmbedBuilder.success(
                "Канал установлен",
                f"Канал для «**{self.label}**» установлен: {channel.mention}",
            ),
            ephemeral=True,
        )


class BackupView(discord.ui.View):
    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=120)
        self.guild_id = guild_id

    @discord.ui.button(label="Создать бэкап", style=discord.ButtonStyle.success, emoji="💾")
    async def create_backup(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        import asyncio, io, json, datetime
        await interaction.response.defer(ephemeral=True)

        async with async_session_maker() as session:
            from database.models import Ticket, TicketForm, TicketPanel, TicketStatus
            from sqlalchemy import select

            tickets_result = await session.execute(
                select(Ticket).where(Ticket.guild_id == self.guild_id)
            )
            tickets = tickets_result.scalars().all()

            forms_result = await session.execute(
                select(TicketForm).where(TicketForm.guild_id == self.guild_id)
            )
            forms = forms_result.scalars().all()

            statuses_result = await session.execute(
                select(TicketStatus).where(TicketStatus.guild_id == self.guild_id)
            )
            statuses = statuses_result.scalars().all()

        data = {
            "guild_id": self.guild_id,
            "exported_at": datetime.datetime.utcnow().isoformat(),
            "tickets_count": len(tickets),
            "forms_count": len(forms),
            "statuses_count": len(statuses),
            "tickets": [
                {
                    "id": t.id,
                    "number": t.number,
                    "author_id": t.author_id,
                    "is_closed": t.is_closed,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in tickets
            ],
        }

        buf = io.BytesIO(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
        ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        await interaction.followup.send(
            embed=EmbedBuilder.success(
                "Бэкап создан",
                f"Экспортировано: {len(tickets)} тикетов, {len(forms)} форм, {len(statuses)} статусов.",
            ),
            file=discord.File(buf, filename=f"backup_{self.guild_id}_{ts}.json"),
            ephemeral=True,
        )
