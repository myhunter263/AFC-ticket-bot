from __future__ import annotations

import discord
from sqlalchemy import delete

from database.models import RecruitmentQuestion, RecruitmentStaffRole
from database.session import async_session_maker
from modules.recruitment.service import RecruitmentError, RecruitmentService
from modules.roles.service import RoleAssignmentError, RolePanelService
from services.audit_service import AuditService
from utils.embeds import EmbedBuilder
from utils.permissions import PermissionChecker


async def _require_admin(interaction: discord.Interaction) -> bool:
    async with async_session_maker() as session:
        allowed = await PermissionChecker.is_bot_admin(interaction, session)
    if not allowed:
        await interaction.response.send_message(
            embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
        )
    return allowed


class AdminOnlyView(discord.ui.View):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _require_admin(interaction)


def settings_embed(settings) -> discord.Embed:
    embed = discord.Embed(
        title="Вступление в клан",
        description="Настройка постоянной панели, формы и recruitment tickets.",
        color=0x5865F2,
    )
    embed.add_field(
        name="Панель",
        value=(
            f"<#{settings.panel_channel_id}> · `{settings.panel_message_id}`"
            if settings.panel_channel_id
            else "Канал не выбран"
        ),
        inline=False,
    )
    embed.add_field(
        name="Категория тикетов",
        value=f"<#{settings.ticket_category_id}>" if settings.ticket_category_id else "Не выбрана",
        inline=True,
    )
    embed.add_field(
        name="Роль после принятия",
        value=f"<@&{settings.accepted_role_id}>" if settings.accepted_role_id else "Не выбрана",
        inline=True,
    )
    staff = ", ".join(f"<@&{row.role_id}>" for row in settings.staff_roles) or "Не выбраны"
    embed.add_field(name="Роли рекрутеров", value=staff[:1024], inline=False)
    embed.add_field(
        name="Форма",
        value=f"{len([q for q in settings.questions if q.enabled])} активных вопросов",
        inline=True,
    )
    embed.add_field(
        name="Повторные активные заявки",
        value="Разрешены" if settings.allow_multiple_active else "Запрещены",
        inline=True,
    )
    embed.add_field(name="Шаблон канала", value=f"`{settings.channel_name_template}`", inline=False)
    return embed


class RecruitmentAdminView(AdminOnlyView):
    def __init__(self, guild_id: int, settings_id: int) -> None:
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.settings_id = settings_id

    @classmethod
    async def create(cls, guild_id: int):
        async with async_session_maker() as session:
            settings = await RecruitmentService.get_or_create_settings(session, guild_id)
            await session.commit()
            settings_id = settings.id
        return cls(guild_id, settings_id)

    @discord.ui.button(label="Текст панели", emoji="✏️", style=discord.ButtonStyle.primary, row=0)
    async def text(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await _require_admin(interaction):
            return
        async with async_session_maker() as session:
            settings = await RecruitmentService.get_settings_by_id(session, self.settings_id)
        await interaction.response.send_modal(RecruitmentPanelTextModal(settings))

    @discord.ui.button(label="Каналы", emoji="📁", style=discord.ButtonStyle.secondary, row=0)
    async def channels(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if await _require_admin(interaction):
            await interaction.response.send_message(
                embed=EmbedBuilder.info(
                    "Каналы recruitment",
                    "Выберите канал постоянной панели и категорию приватных тикетов.",
                ),
                view=RecruitmentChannelsView(self.guild_id, self.settings_id),
                ephemeral=True,
            )

    @discord.ui.button(label="Роли", emoji="👥", style=discord.ButtonStyle.secondary, row=0)
    async def roles(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if await _require_admin(interaction):
            await interaction.response.send_message(
                embed=EmbedBuilder.info(
                    "Роли recruitment",
                    "Выберите роли рекрутеров и отдельную роль, выдаваемую после принятия.",
                ),
                view=RecruitmentRolesView(self.guild_id, self.settings_id),
                ephemeral=True,
            )

    @discord.ui.button(label="Настроить форму", emoji="📋", style=discord.ButtonStyle.primary, row=1)
    async def form(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await _require_admin(interaction):
            return
        async with async_session_maker() as session:
            settings = await RecruitmentService.get_settings_by_id(session, self.settings_id)
        await interaction.response.send_message(
            embed=form_embed(settings),
            view=RecruitmentFormAdminView(self.guild_id, self.settings_id, settings.questions),
            ephemeral=True,
        )

    @discord.ui.button(label="Повторные заявки", emoji="🔁", style=discord.ButtonStyle.secondary, row=1)
    async def multiple(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await _require_admin(interaction):
            return
        async with async_session_maker() as session:
            settings = await RecruitmentService.get_settings_by_id(session, self.settings_id)
            settings.allow_multiple_active = not settings.allow_multiple_active
            await session.commit()
            enabled = settings.allow_multiple_active
        await interaction.response.send_message(
            embed=EmbedBuilder.success(
                "Настройка сохранена",
                "Повторные активные заявки разрешены." if enabled else "Повторные активные заявки запрещены.",
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Опубликовать/обновить", emoji="💾", style=discord.ButtonStyle.success, row=2)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await _require_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            settings = await RecruitmentService.publish_panel(
                interaction.client, self.settings_id, actor=interaction.user
            )
        except (RecruitmentError, discord.HTTPException) as exc:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Панель не опубликована", str(exc)), ephemeral=True
            )
            return
        await interaction.followup.send(
            embed=EmbedBuilder.success(
                "Панель обновлена",
                f"Постоянное сообщение: `{settings.panel_message_id}`.",
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Удалить сообщение панели", emoji="🗑️", style=discord.ButtonStyle.danger, row=2)
    async def remove_panel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await _require_admin(interaction):
            return
        async with async_session_maker() as session:
            settings = await RecruitmentService.get_settings_by_id(session, self.settings_id)
            channel = interaction.guild.get_channel(settings.panel_channel_id) if settings.panel_channel_id else None
            if isinstance(channel, discord.TextChannel) and settings.panel_message_id:
                try:
                    message = await channel.fetch_message(settings.panel_message_id)
                    await message.delete(reason=f"Recruitment panel deleted by {interaction.user}")
                except (discord.NotFound, discord.HTTPException):
                    pass
            settings.panel_message_id = None
            await AuditService.log(
                session,
                guild_id=self.guild_id,
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action="PANEL_DELETED",
                target_type="RECRUITMENT_PANEL",
                target_id=settings.id,
            )
            await session.commit()
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Сообщение панели удалено", "Настройки и форма сохранены."),
            ephemeral=True,
        )


class RecruitmentPanelTextModal(discord.ui.Modal, title="Панель вступления"):
    def __init__(self, settings) -> None:
        super().__init__()
        self.settings_id = settings.id
        self.title_input = discord.ui.TextInput(
            label="Название", default=settings.panel_title, max_length=100
        )
        self.description_input = discord.ui.TextInput(
            label="Описание", default=settings.panel_description or "", required=False,
            style=discord.TextStyle.paragraph, max_length=2000,
        )
        self.button_input = discord.ui.TextInput(
            label="Текст кнопки", default=settings.button_label, max_length=80
        )
        self.emoji_input = discord.ui.TextInput(
            label="Emoji кнопки", default=settings.button_emoji or "", required=False, max_length=100
        )
        self.template_input = discord.ui.TextInput(
            label="Шаблон канала",
            default=settings.channel_name_template,
            max_length=100,
            placeholder="recruit-{application_id} или recruit-{username}",
        )
        for item in (
            self.title_input, self.description_input, self.button_input,
            self.emoji_input, self.template_input,
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        template = str(self.template_input)
        if "{application_id}" not in template and "{username}" not in template:
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "Некорректный шаблон", "Добавьте {application_id} или {username}."
                ),
                ephemeral=True,
            )
            return
        async with async_session_maker() as session:
            settings = await RecruitmentService.get_settings_by_id(session, self.settings_id)
            settings.panel_title = str(self.title_input)
            settings.panel_description = str(self.description_input) or None
            settings.button_label = str(self.button_input)
            settings.button_emoji = str(self.emoji_input) or None
            settings.channel_name_template = template
            await session.commit()
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Настройки панели сохранены"), ephemeral=True
        )


class RecruitmentChannelsView(AdminOnlyView):
    def __init__(self, guild_id: int, settings_id: int) -> None:
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.settings_id = settings_id
        self.panel_channel = discord.ui.ChannelSelect(
            placeholder="Канал постоянной панели",
            channel_types=[discord.ChannelType.text], row=0,
        )
        self.panel_channel.callback = self._panel_selected
        self.add_item(self.panel_channel)
        self.ticket_category = discord.ui.ChannelSelect(
            placeholder="Категория recruitment tickets",
            channel_types=[discord.ChannelType.category], row=1,
        )
        self.ticket_category.callback = self._category_selected
        self.add_item(self.ticket_category)

    async def _panel_selected(self, interaction: discord.Interaction) -> None:
        channel = self.panel_channel.values[0]
        async with async_session_maker() as session:
            settings = await RecruitmentService.get_settings_by_id(session, self.settings_id)
            if settings.panel_message_id and settings.panel_channel_id != channel.id:
                old_channel = interaction.guild.get_channel(settings.panel_channel_id)
                if isinstance(old_channel, discord.TextChannel):
                    try:
                        old_message = await old_channel.fetch_message(settings.panel_message_id)
                        await old_message.delete(reason=f"Recruitment panel moved by {interaction.user}")
                    except (discord.NotFound, discord.HTTPException):
                        pass
                settings.panel_message_id = None
            settings.panel_channel_id = channel.id
            await session.commit()
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Канал панели сохранён", channel.mention), ephemeral=True
        )

    async def _category_selected(self, interaction: discord.Interaction) -> None:
        category = self.ticket_category.values[0]
        async with async_session_maker() as session:
            settings = await RecruitmentService.get_settings_by_id(session, self.settings_id)
            settings.ticket_category_id = category.id
            await session.commit()
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Категория тикетов сохранена", category.mention), ephemeral=True
        )


class RecruitmentRolesView(AdminOnlyView):
    def __init__(self, guild_id: int, settings_id: int) -> None:
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.settings_id = settings_id
        self.staff_select = discord.ui.RoleSelect(
            placeholder="Роли рекрутеров", min_values=1, max_values=10, row=0
        )
        self.staff_select.callback = self._staff_selected
        self.add_item(self.staff_select)
        self.accepted_select = discord.ui.RoleSelect(
            placeholder="Роль после принятия", min_values=1, max_values=1, row=1
        )
        self.accepted_select.callback = self._accepted_selected
        self.add_item(self.accepted_select)

    async def _staff_selected(self, interaction: discord.Interaction) -> None:
        roles = list(self.staff_select.values)
        for role in roles:
            if role.is_default() or role.managed:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Недопустимая роль", role.name), ephemeral=True
                )
                return
        async with async_session_maker() as session:
            await session.execute(
                delete(RecruitmentStaffRole).where(
                    RecruitmentStaffRole.settings_id == self.settings_id
                )
            )
            session.add_all([
                RecruitmentStaffRole(settings_id=self.settings_id, role_id=role.id)
                for role in roles
            ])
            await session.commit()
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Роли рекрутеров сохранены"), ephemeral=True
        )

    async def _accepted_selected(self, interaction: discord.Interaction) -> None:
        role = self.accepted_select.values[0]
        try:
            RolePanelService.validate_assignable(interaction.guild, role)
        except RoleAssignmentError as exc:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Роль нельзя выдавать", str(exc)), ephemeral=True
            )
            return
        async with async_session_maker() as session:
            settings = await RecruitmentService.get_settings_by_id(session, self.settings_id)
            settings.accepted_role_id = role.id
            await session.commit()
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Роль после принятия сохранена", role.mention), ephemeral=True
        )

    @discord.ui.button(
        label="Очистить роли рекрутеров",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def clear_staff(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        async with async_session_maker() as session:
            await session.execute(
                delete(RecruitmentStaffRole).where(
                    RecruitmentStaffRole.settings_id == self.settings_id
                )
            )
            await session.commit()
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Роли рекрутеров очищены"), ephemeral=True
        )

    @discord.ui.button(
        label="Убрать автороль",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def clear_accepted(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        async with async_session_maker() as session:
            settings = await RecruitmentService.get_settings_by_id(session, self.settings_id)
            settings.accepted_role_id = None
            await session.commit()
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Роль после принятия очищена"), ephemeral=True
        )


def form_embed(settings) -> discord.Embed:
    embed = discord.Embed(
        title="Форма вступления",
        description=(
            "До 20 вопросов. Discord показывает по 5 полей за шаг; "
            "длинная форма автоматически становится многошаговой."
        ),
        color=0x5865F2,
    )
    for index, question in enumerate(settings.questions, start=1):
        embed.add_field(
            name=f"{index}. {question.label}",
            value=(
                f"`{question.input_style}` · "
                f"{'обязательный' if question.required else 'необязательный'} · "
                f"{question.min_length}–{question.max_length}"
            ),
            inline=False,
        )
    return embed


class RecruitmentFormAdminView(AdminOnlyView):
    def __init__(self, guild_id: int, settings_id: int, questions: list) -> None:
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.settings_id = settings_id
        if questions:
            select = discord.ui.Select(
                placeholder="Изменить вопрос",
                options=[
                    discord.SelectOption(label=row.label[:100], value=str(row.id))
                    for row in questions[:20]
                ],
                row=0,
            )
            select.callback = self._selected
            self.add_item(select)

    async def _selected(self, interaction: discord.Interaction) -> None:
        question_id = int(interaction.data["values"][0])
        await interaction.response.send_message(
            embed=EmbedBuilder.info("Вопрос формы", "Выберите действие."),
            view=RecruitmentQuestionActions(self.settings_id, question_id),
            ephemeral=True,
        )

    @discord.ui.button(label="Добавить вопрос", emoji="➕", style=discord.ButtonStyle.success, row=1)
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(RecruitmentQuestionModal(self.settings_id))


class RecruitmentQuestionActions(AdminOnlyView):
    def __init__(self, settings_id: int, question_id: int) -> None:
        super().__init__(timeout=180)
        self.settings_id = settings_id
        self.question_id = question_id

    @discord.ui.button(label="Редактировать", emoji="✏️", style=discord.ButtonStyle.primary)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            question = await session.get(RecruitmentQuestion, self.question_id)
        await interaction.response.send_modal(
            RecruitmentQuestionModal(self.settings_id, question)
        )

    async def _move(self, interaction: discord.Interaction, direction: int) -> None:
        async with async_session_maker() as session:
            question = await session.get(RecruitmentQuestion, self.question_id)
            if question:
                await RecruitmentService.move_question(session, question, direction)
                await session.commit()
        await interaction.response.edit_message(
            embed=EmbedBuilder.success("Порядок изменён"), view=None
        )

    @discord.ui.button(label="Выше", emoji="⬆️", style=discord.ButtonStyle.secondary)
    async def up(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._move(interaction, -1)

    @discord.ui.button(label="Ниже", emoji="⬇️", style=discord.ButtonStyle.secondary)
    async def down(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._move(interaction, 1)

    @discord.ui.button(label="Удалить", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def remove(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            question = await session.get(RecruitmentQuestion, self.question_id)
            if question:
                await session.delete(question)
                await session.commit()
        await interaction.response.edit_message(
            embed=EmbedBuilder.success("Вопрос удалён"), view=None
        )


class RecruitmentQuestionModal(discord.ui.Modal, title="Вопрос формы"):
    def __init__(self, settings_id: int, question=None) -> None:
        super().__init__()
        self.settings_id = settings_id
        self.question_id = question.id if question else None
        self.label_input = discord.ui.TextInput(
            label="Вопрос", default=question.label if question else "", max_length=45
        )
        self.placeholder_input = discord.ui.TextInput(
            label="Placeholder", default=(question.placeholder or "") if question else "",
            required=False, max_length=100,
        )
        self.style_input = discord.ui.TextInput(
            label="Тип: short или paragraph",
            default=question.input_style if question else "short", max_length=9,
        )
        self.required_input = discord.ui.TextInput(
            label="Обязательный: да или нет",
            default="да" if question is None or question.required else "нет", max_length=3,
        )
        self.length_input = discord.ui.TextInput(
            label="Мин,макс длина",
            default=(
                f"{question.min_length},{question.max_length}" if question else "0,1024"
            ),
            max_length=9,
        )
        for item in (
            self.label_input, self.placeholder_input, self.style_input,
            self.required_input, self.length_input,
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        style = str(self.style_input).strip().casefold()
        required_text = str(self.required_input).strip().casefold()
        try:
            min_length, max_length = [
                int(part.strip()) for part in str(self.length_input).split(",", 1)
            ]
        except (ValueError, TypeError):
            min_length, max_length = -1, -1
        if style not in {"short", "paragraph"}:
            error = "Тип должен быть short или paragraph."
        elif required_text not in {"да", "нет", "yes", "no"}:
            error = "Обязательность должна быть «да» или «нет»."
        elif min_length < 0 or max_length < 1 or min_length > max_length or max_length > 4000:
            error = "Длина должна иметь формат 0,1024; максимум 4000."
        else:
            error = None
        if error:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Некорректный вопрос", error), ephemeral=True
            )
            return
        required = required_text in {"да", "yes"}
        async with async_session_maker() as session:
            settings = await RecruitmentService.get_settings_by_id(session, self.settings_id)
            if self.question_id:
                question = await session.get(RecruitmentQuestion, self.question_id)
                question.label = str(self.label_input)
                question.placeholder = str(self.placeholder_input) or None
                question.input_style = style
                question.required = required
                question.min_length = min_length
                question.max_length = max_length
            else:
                try:
                    await RecruitmentService.add_question(
                        session,
                        settings,
                        label=str(self.label_input),
                        placeholder=str(self.placeholder_input) or None,
                        input_style=style,
                        required=required,
                        min_length=min_length,
                        max_length=max_length,
                    )
                except RecruitmentError as exc:
                    await interaction.response.send_message(
                        embed=EmbedBuilder.error("Вопрос не добавлен", str(exc)), ephemeral=True
                    )
                    return
            await session.commit()
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Вопрос сохранён"), ephemeral=True
        )
