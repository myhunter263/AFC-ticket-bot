from __future__ import annotations

import discord

from config import config
from database.session import async_session_maker
from modules.roles.service import RoleAssignmentError, RolePanelService
from services.audit_service import AuditService
from utils.embeds import EmbedBuilder
from utils.permissions import PermissionChecker


def _parse_color(value: str) -> int:
    cleaned = value.strip().removeprefix("#")
    try:
        return int(cleaned, 16) if cleaned else config.COLOR_PRIMARY
    except ValueError as exc:
        raise ValueError("Цвет должен быть HEX, например 5865F2.") from exc


async def _is_admin(interaction: discord.Interaction) -> bool:
    async with async_session_maker() as session:
        allowed = await PermissionChecker.is_bot_admin(interaction, session)
    if not allowed:
        await interaction.response.send_message(
            embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
        )
    return allowed


class AdminOnlyView(discord.ui.View):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _is_admin(interaction)


def _panel_embed(panel) -> discord.Embed:
    embed = discord.Embed(
        title=f"Панель ролей: {panel.title}",
        description=panel.description or "Описание не задано.",
        color=panel.color,
    )
    embed.add_field(name="Канал", value=f"<#{panel.panel_channel_id}>", inline=True)
    embed.add_field(
        name="Сообщение",
        value=str(panel.panel_message_id or "ещё не опубликовано"),
        inline=True,
    )
    roles = "\n".join(
        f"{index}. <@&{item.role_id}> — {item.emoji or ''} {item.label}"
        for index, item in enumerate(panel.items, start=1)
    ) or "Роли ещё не добавлены."
    embed.add_field(name="Кнопки", value=roles[:1024], inline=False)
    return embed


class RolePanelAdminView(AdminOnlyView):
    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=300)
        self.guild_id = guild_id

    @discord.ui.button(label="Создать панель", emoji="➕", style=discord.ButtonStyle.success)
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if await _is_admin(interaction):
            await interaction.response.send_modal(RolePanelCreateModal(self.guild_id))

    @discord.ui.button(label="Список и настройка", emoji="⚙️", style=discord.ButtonStyle.primary)
    async def list_panels(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await _is_admin(interaction):
            return
        async with async_session_maker() as session:
            panels = await RolePanelService.list_panels(session, self.guild_id)
        if not panels:
            await interaction.response.send_message(
                embed=EmbedBuilder.info("Панели ролей", "Панелей ещё нет."), ephemeral=True
            )
            return
        select = discord.ui.Select(
            placeholder="Выберите панель ролей",
            options=[
                discord.SelectOption(
                    label=panel.title[:100],
                    value=str(panel.id),
                    description=f"{len(panel.items)} ролей · канал {panel.panel_channel_id}",
                )
                for panel in panels[:25]
            ],
        )
        view = discord.ui.View(timeout=180)

        async def selected(select_interaction: discord.Interaction) -> None:
            panel_id = int(select.values[0])
            async with async_session_maker() as session:
                panel = await RolePanelService.get_panel(session, panel_id)
            if panel is None:
                await select_interaction.response.send_message(
                    embed=EmbedBuilder.error("Панель не найдена"), ephemeral=True
                )
                return
            await select_interaction.response.edit_message(
                embed=_panel_embed(panel), view=RolePanelEditorView(panel.id)
            )

        select.callback = selected
        view.add_item(select)
        await interaction.response.send_message(
            embed=EmbedBuilder.info("Панели ролей", "Выберите панель для настройки."),
            view=view,
            ephemeral=True,
        )


class RolePanelCreateModal(discord.ui.Modal, title="Новая панель ролей"):
    panel_title = discord.ui.TextInput(label="Название", max_length=100)
    description = discord.ui.TextInput(
        label="Описание", style=discord.TextStyle.paragraph, required=False, max_length=2000
    )
    color = discord.ui.TextInput(
        label="HEX-цвет", default="5865F2", required=False, max_length=6
    )

    def __init__(self, guild_id: int) -> None:
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            color = _parse_color(str(self.color))
        except ValueError as exc:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Некорректный цвет", str(exc)), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=EmbedBuilder.info(
                "Канал панели", "Выберите текстовый канал. После этого добавьте роли и опубликуйте панель."
            ),
            view=RolePanelDestinationView(
                self.guild_id,
                str(self.panel_title),
                str(self.description) or None,
                color,
            ),
            ephemeral=True,
        )


class RolePanelDestinationView(AdminOnlyView):
    def __init__(self, guild_id: int, title: str, description: str | None, color: int) -> None:
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.title = title
        self.description = description
        self.color = color
        select = discord.ui.ChannelSelect(
            placeholder="Канал размещения",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )
        select.callback = self._selected
        self.channel_select = select
        self.add_item(select)

    async def _selected(self, interaction: discord.Interaction) -> None:
        channel_id = self.channel_select.values[0].id
        async with async_session_maker() as session:
            panel = await RolePanelService.create_panel(
                session,
                guild_id=self.guild_id,
                channel_id=channel_id,
                title=self.title,
                description=self.description,
                color=self.color,
                created_by=interaction.user.id,
            )
            await AuditService.log(
                session,
                guild_id=self.guild_id,
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action="PANEL_CREATED",
                target_type="ROLE_PANEL",
                target_id=panel.id,
            )
            await session.commit()
            panel_id = panel.id
        async with async_session_maker() as session:
            panel = await RolePanelService.get_panel(session, panel_id)
        await interaction.response.edit_message(
            embed=_panel_embed(panel), view=RolePanelEditorView(panel_id)
        )


class RolePanelEditorView(AdminOnlyView):
    def __init__(self, panel_id: int) -> None:
        super().__init__(timeout=300)
        self.panel_id = panel_id
        role_select = discord.ui.RoleSelect(
            placeholder="Добавить Discord-роль",
            min_values=1,
            max_values=1,
            row=0,
        )
        role_select.callback = self._add_role
        self.add_item(role_select)
        channel_select = discord.ui.ChannelSelect(
            placeholder="Перенести панель в другой канал",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=1,
        )
        channel_select.callback = self._change_channel
        self.add_item(channel_select)

    async def _reload(self, interaction: discord.Interaction) -> None:
        async with async_session_maker() as session:
            panel = await RolePanelService.get_panel(session, self.panel_id)
        await interaction.response.edit_message(
            embed=_panel_embed(panel), view=RolePanelEditorView(self.panel_id)
        )

    async def _add_role(self, interaction: discord.Interaction) -> None:
        role_id = int(interaction.data["values"][0])
        role = interaction.guild.get_role(role_id)
        try:
            if role is None:
                raise RoleAssignmentError("Роль не найдена.")
            RolePanelService.validate_assignable(interaction.guild, role)
            async with async_session_maker() as session:
                panel = await RolePanelService.get_panel(session, self.panel_id)
                await RolePanelService.add_item(session, panel, role)
                await session.commit()
        except RoleAssignmentError as exc:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Роль нельзя добавить", str(exc)), ephemeral=True
            )
            return
        await self._reload(interaction)

    async def _change_channel(self, interaction: discord.Interaction) -> None:
        new_channel_id = int(interaction.data["values"][0])
        async with async_session_maker() as session:
            panel = await RolePanelService.get_panel(session, self.panel_id)
            if panel is None:
                return
            old_channel = interaction.guild.get_channel(panel.panel_channel_id)
            if isinstance(old_channel, discord.TextChannel) and panel.panel_message_id:
                try:
                    old_message = await old_channel.fetch_message(panel.panel_message_id)
                    await old_message.delete(reason=f"Role panel moved by {interaction.user}")
                except (discord.NotFound, discord.HTTPException):
                    pass
            panel.panel_channel_id = new_channel_id
            panel.panel_message_id = None
            await session.commit()
        await self._reload(interaction)

    @discord.ui.button(label="Текст", emoji="✏️", style=discord.ButtonStyle.secondary, row=2)
    async def edit_text(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            panel = await RolePanelService.get_panel(session, self.panel_id)
        await interaction.response.send_modal(RolePanelTextModal(panel))

    @discord.ui.button(label="Кнопки", emoji="🔘", style=discord.ButtonStyle.secondary, row=2)
    async def manage_items(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            panel = await RolePanelService.get_panel(session, self.panel_id)
        if not panel or not panel.items:
            await interaction.response.send_message(
                embed=EmbedBuilder.info("Кнопки ролей", "Сначала добавьте роль."), ephemeral=True
            )
            return
        select = discord.ui.Select(
            placeholder="Кнопка для редактирования",
            options=[
                discord.SelectOption(label=item.label[:100], value=str(item.id))
                for item in panel.items[:25]
            ],
        )
        view = discord.ui.View(timeout=180)

        async def selected(select_interaction: discord.Interaction) -> None:
            item_id = int(select.values[0])
            await select_interaction.response.edit_message(
                embed=EmbedBuilder.info("Кнопка роли", "Измените подпись, порядок или удалите кнопку."),
                view=RoleItemEditorView(self.panel_id, item_id),
            )

        select.callback = selected
        view.add_item(select)
        await interaction.response.send_message(
            embed=EmbedBuilder.info("Кнопки ролей", "Выберите кнопку."),
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="Опубликовать/обновить", emoji="💾", style=discord.ButtonStyle.success, row=3)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            panel = await RolePanelService.get_panel(session, self.panel_id)
        if panel is None or not panel.items:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Нет ролей", "Добавьте минимум одну роль."), ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        try:
            panel = await RolePanelService.publish(
                interaction.client, self.panel_id, actor=interaction.user
            )
        except (RoleAssignmentError, discord.HTTPException) as exc:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Публикация не удалась", str(exc)), ephemeral=True
            )
            return
        await interaction.followup.send(
            embed=EmbedBuilder.success(
                "Панель опубликована", f"Сообщение `{panel.panel_message_id}` обновлено."
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Удалить", emoji="🗑️", style=discord.ButtonStyle.danger, row=3)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            panel = await RolePanelService.get_panel(session, self.panel_id)
            if panel:
                await RolePanelService.delete_panel(session, interaction.client, panel, interaction.user)
                await session.commit()
        await interaction.response.edit_message(
            embed=EmbedBuilder.success("Панель удалена"), view=None
        )


class RolePanelTextModal(discord.ui.Modal, title="Текст панели ролей"):
    def __init__(self, panel) -> None:
        super().__init__()
        self.panel_id = panel.id
        self.title_input = discord.ui.TextInput(
            label="Название", default=panel.title, max_length=100
        )
        self.description_input = discord.ui.TextInput(
            label="Описание",
            default=panel.description or "",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=2000,
        )
        self.color_input = discord.ui.TextInput(
            label="HEX-цвет", default=f"{panel.color:06X}", required=False, max_length=6
        )
        self.add_item(self.title_input)
        self.add_item(self.description_input)
        self.add_item(self.color_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            color = _parse_color(str(self.color_input))
        except ValueError as exc:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Некорректный цвет", str(exc)), ephemeral=True
            )
            return
        async with async_session_maker() as session:
            panel = await RolePanelService.get_panel(session, self.panel_id)
            panel.title = str(self.title_input)
            panel.description = str(self.description_input) or None
            panel.color = color
            await session.commit()
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Текст сохранён", "Нажмите «Опубликовать/обновить»."),
            ephemeral=True,
        )


class RoleItemEditorView(AdminOnlyView):
    def __init__(self, panel_id: int, item_id: int) -> None:
        super().__init__(timeout=180)
        self.panel_id = panel_id
        self.item_id = item_id
        role_select = discord.ui.RoleSelect(
            placeholder="Заменить Discord-роль",
            min_values=1,
            max_values=1,
            row=0,
        )
        role_select.callback = self._replace_role
        self.role_select = role_select
        self.add_item(role_select)

    async def _replace_role(self, interaction: discord.Interaction) -> None:
        role = self.role_select.values[0]
        try:
            RolePanelService.validate_assignable(interaction.guild, role)
            async with async_session_maker() as session:
                item = await RolePanelService.get_item(session, self.item_id)
                if item is None:
                    raise RoleAssignmentError("Кнопка роли не найдена.")
                await RolePanelService.replace_item_role(session, item, role)
                await session.commit()
        except RoleAssignmentError as exc:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Роль не заменена", str(exc)), ephemeral=True
            )
            return
        await interaction.response.edit_message(
            embed=EmbedBuilder.success("Роль кнопки заменена"), view=None
        )

    @discord.ui.button(label="Подпись и emoji", style=discord.ButtonStyle.primary, row=1)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            item = await RolePanelService.get_item(session, self.item_id)
        await interaction.response.send_modal(RoleItemEditModal(item))

    async def _move(self, interaction: discord.Interaction, direction: int) -> None:
        async with async_session_maker() as session:
            item = await RolePanelService.get_item(session, self.item_id)
            if item:
                await RolePanelService.move_item(session, item, direction)
                await session.commit()
        await interaction.response.edit_message(
            embed=EmbedBuilder.success("Порядок изменён"), view=None
        )

    @discord.ui.button(label="Выше", emoji="⬆️", style=discord.ButtonStyle.secondary, row=1)
    async def up(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._move(interaction, -1)

    @discord.ui.button(label="Ниже", emoji="⬇️", style=discord.ButtonStyle.secondary, row=1)
    async def down(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._move(interaction, 1)

    @discord.ui.button(label="Удалить", emoji="🗑️", style=discord.ButtonStyle.danger, row=1)
    async def remove(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            item = await RolePanelService.get_item(session, self.item_id)
            if item:
                await RolePanelService.remove_item(session, item)
                await session.commit()
        await interaction.response.edit_message(
            embed=EmbedBuilder.success("Кнопка удалена"), view=None
        )


class RoleItemEditModal(discord.ui.Modal, title="Кнопка роли"):
    def __init__(self, item) -> None:
        super().__init__()
        self.item_id = item.id
        self.label_input = discord.ui.TextInput(label="Подпись", default=item.label, max_length=80)
        self.emoji_input = discord.ui.TextInput(
            label="Emoji", default=item.emoji or "", required=False, max_length=100
        )
        self.add_item(self.label_input)
        self.add_item(self.emoji_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        async with async_session_maker() as session:
            item = await RolePanelService.get_item(session, self.item_id)
            item.label = str(self.label_input)
            item.emoji = str(self.emoji_input) or None
            await session.commit()
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Кнопка сохранена", "Обновите сообщение панели."),
            ephemeral=True,
        )
