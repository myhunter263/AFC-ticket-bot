from __future__ import annotations

import logging

import discord

from database.session import async_session_maker
from modules.recruitment.service import RecruitmentError, RecruitmentService
from utils.embeds import EmbedBuilder
from utils.permissions import PermissionChecker

logger = logging.getLogger(__name__)


class RecruitmentPanelView(discord.ui.View):
    message_type = "PERMANENT_RECRUITMENT_PANEL"

    def __init__(
        self,
        settings_id: int,
        button_label: str = "Подать заявку",
        button_emoji: str | None = None,
    ) -> None:
        super().__init__(timeout=None)
        self.settings_id = settings_id
        button = discord.ui.Button(
            label=button_label[:80],
            emoji=button_emoji or None,
            style=discord.ButtonStyle.primary,
            custom_id=f"recruitment:apply:{settings_id}",
        )
        button.callback = self._apply
        self.add_item(button)

    async def _apply(self, interaction: discord.Interaction) -> None:
        async with async_session_maker() as session:
            settings = await RecruitmentService.get_settings_by_id(session, self.settings_id)
            if settings is None or settings.guild_id != interaction.guild_id or not settings.enabled:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Приём заявок отключён"), ephemeral=True
                )
                return
            if not settings.allow_multiple_active:
                active = await RecruitmentService.active_for_user(
                    session, interaction.guild_id, interaction.user.id
                )
                if active:
                    channel = f" <#{active.ticket_channel_id}>" if active.ticket_channel_id else ""
                    await interaction.response.send_message(
                        embed=EmbedBuilder.info(
                            "Заявка уже существует",
                            f"У вас уже есть активная заявка #{active.id}.{channel}",
                        ),
                        ephemeral=True,
                    )
                    return
            questions = RecruitmentService.enabled_questions(settings)
        if not questions:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Форма не настроена"), ephemeral=True
            )
            return
        state = RecruitmentFormState(
            settings_id=self.settings_id,
            author_id=interaction.user.id,
            questions=[
                {
                    "id": row.id,
                    "label": row.label,
                    "placeholder": row.placeholder,
                    "input_style": row.input_style,
                    "required": row.required,
                    "min_length": row.min_length,
                    "max_length": row.max_length,
                }
                for row in questions
            ],
        )
        await interaction.response.send_modal(RecruitmentPageModal(state, 0))


class RecruitmentFormState:
    def __init__(self, settings_id: int, author_id: int, questions: list[dict]) -> None:
        self.settings_id = settings_id
        self.author_id = author_id
        self.questions = questions
        self.answers: list[dict] = []


class RecruitmentPageModal(discord.ui.Modal):
    def __init__(self, state: RecruitmentFormState, offset: int) -> None:
        page = offset // 5 + 1
        pages = (len(state.questions) + 4) // 5
        super().__init__(title=f"Заявка на вступление · {page}/{pages}")
        self.state = state
        self.offset = offset
        self.page_questions = state.questions[offset:offset + 5]
        for question in self.page_questions:
            self.add_item(discord.ui.TextInput(
                label=question["label"][:45],
                placeholder=question.get("placeholder") or None,
                style=(
                    discord.TextStyle.paragraph
                    if question.get("input_style") == "paragraph"
                    else discord.TextStyle.short
                ),
                required=question.get("required", True),
                min_length=max(0, question.get("min_length", 0)),
                max_length=min(4000, question.get("max_length", 1024)),
            ))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.state.author_id:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Это форма другого пользователя."), ephemeral=True
            )
            return
        for question, input_item in zip(self.page_questions, self.children):
            self.state.answers.append({
                "question_id": question["id"],
                "label": question["label"],
                "value": input_item.value,
            })
        next_offset = self.offset + len(self.page_questions)
        if next_offset < len(self.state.questions):
            await interaction.response.send_message(
                embed=EmbedBuilder.info(
                    "Форма сохранена",
                    "Нажмите «Продолжить», чтобы заполнить следующую часть.",
                ),
                view=RecruitmentContinueView(self.state, next_offset),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            application = await RecruitmentService.create_application(
                interaction, self.state.settings_id, self.state.answers
            )
        except (RecruitmentError, discord.HTTPException) as exc:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Заявка не создана", str(exc)), ephemeral=True
            )
            return
        await interaction.followup.send(
            embed=EmbedBuilder.success(
                "Заявка создана",
                f"Ваша заявка #{application.id}: <#{application.ticket_channel_id}>",
            ),
            ephemeral=True,
        )


class RecruitmentContinueView(discord.ui.View):
    def __init__(self, state: RecruitmentFormState, offset: int) -> None:
        super().__init__(timeout=600)
        self.state = state
        self.offset = offset

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.state.author_id:
            return True
        await interaction.response.send_message(
            embed=EmbedBuilder.error("Это форма другого пользователя."), ephemeral=True
        )
        return False

    @discord.ui.button(label="Продолжить", emoji="➡️", style=discord.ButtonStyle.primary)
    async def continue_form(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(RecruitmentPageModal(self.state, self.offset))


class RecruitmentTicketView(discord.ui.View):
    message_type = "RECRUITMENT_TICKET_MESSAGE"

    def __init__(
        self,
        application_id: int,
        guild_id: int,
        *,
        status: str = "PENDING",
        closed: bool = False,
    ) -> None:
        super().__init__(timeout=None)
        self.application_id = application_id
        self.guild_id = guild_id
        self.accept.disabled = status != "PENDING" or closed
        self.reject.disabled = status != "PENDING" or closed
        self.close.disabled = status == "PENDING" or closed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        async with async_session_maker() as session:
            allowed = await PermissionChecker.is_recruitment_staff(interaction, session)
        if allowed:
            return True
        await interaction.response.send_message(
            embed=EmbedBuilder.error("Нет доступа", "Требуется роль рекрутера."),
            ephemeral=True,
        )
        return False

    @discord.ui.button(
        label="Принять", emoji="✅", style=discord.ButtonStyle.success,
        custom_id="recruitment_ticket:accept",
    )
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            application = await RecruitmentService.get_application(session, self.application_id)
        if application and application.user_id == interaction.user.id:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Нельзя принять собственную заявку."), ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await RecruitmentService.review(
                interaction, self.application_id, "ACCEPTED"
            )
            await RecruitmentService.refresh_message(interaction.client, self.application_id)
        except RecruitmentError as exc:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Решение не сохранено", str(exc)), ephemeral=True
            )
            return
        await interaction.followup.send(
            embed=EmbedBuilder.success("Заявка принята"), ephemeral=True
        )

    @discord.ui.button(
        label="Отклонить", emoji="❌", style=discord.ButtonStyle.danger,
        custom_id="recruitment_ticket:reject",
    )
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(RecruitmentRejectModal(self.application_id))

    @discord.ui.button(
        label="Закрыть", emoji="🔒", style=discord.ButtonStyle.secondary,
        custom_id="recruitment_ticket:close",
    )
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await RecruitmentService.close(interaction, self.application_id)
            await RecruitmentService.refresh_message(interaction.client, self.application_id)
        except (RecruitmentError, discord.HTTPException) as exc:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Не удалось закрыть", str(exc)), ephemeral=True
            )
            return
        await interaction.followup.send(
            embed=EmbedBuilder.success("Заявка закрыта", "Канал сохранён в архивном состоянии."),
            ephemeral=True,
        )


class RecruitmentRejectModal(discord.ui.Modal, title="Отклонение заявки"):
    reason = discord.ui.TextInput(
        label="Причина отказа",
        style=discord.TextStyle.paragraph,
        min_length=2,
        max_length=1000,
    )

    def __init__(self, application_id: int) -> None:
        super().__init__()
        self.application_id = application_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        async with async_session_maker() as session:
            allowed = await PermissionChecker.is_recruitment_staff(interaction, session)
        if not allowed:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await RecruitmentService.review(
                interaction, self.application_id, "REJECTED", str(self.reason)
            )
            await RecruitmentService.refresh_message(interaction.client, self.application_id)
        except RecruitmentError as exc:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Решение не сохранено", str(exc)), ephemeral=True
            )
            return
        await interaction.followup.send(
            embed=EmbedBuilder.success("Заявка отклонена"), ephemeral=True
        )
