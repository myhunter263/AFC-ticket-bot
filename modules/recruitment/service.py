from __future__ import annotations

import datetime
import logging
import re

import discord
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    RecruitmentApplication,
    RecruitmentQuestion,
    RecruitmentSettings,
    RecruitmentStaffRole,
)
from services.audit_service import AuditService

logger = logging.getLogger(__name__)


class RecruitmentError(ValueError):
    pass


class RecruitmentService:
    DEFAULT_QUESTIONS = [
        ("Игровой ник", "Ваш игровой ник", "short", True, 2, 100),
        ("Возраст", "Ваш возраст", "short", True, 1, 20),
        ("Опыт в Foxhole", "Расскажите об опыте", "paragraph", True, 0, 1000),
        ("Предпочтения", "Чем предпочитаете заниматься?", "paragraph", True, 0, 1000),
        ("Почему хотите вступить?", None, "paragraph", True, 0, 1500),
    ]

    @classmethod
    async def get_or_create_settings(
        cls, session: AsyncSession, guild_id: int
    ) -> RecruitmentSettings:
        settings = await cls.get_settings(session, guild_id)
        if settings is not None:
            return settings
        settings = RecruitmentSettings(
            guild_id=guild_id,
            panel_description="Хотите присоединиться? Заполните небольшую заявку.",
        )
        session.add(settings)
        await session.flush()
        for position, row in enumerate(cls.DEFAULT_QUESTIONS, start=1):
            label, placeholder, style, required, min_length, max_length = row
            session.add(RecruitmentQuestion(
                settings_id=settings.id,
                label=label,
                placeholder=placeholder,
                input_style=style,
                required=required,
                min_length=min_length,
                max_length=max_length,
                position=position,
            ))
        await session.flush()
        return await cls.get_settings(session, guild_id)

    @staticmethod
    async def get_settings(
        session: AsyncSession, guild_id: int
    ) -> RecruitmentSettings | None:
        result = await session.execute(
            select(RecruitmentSettings)
            .where(RecruitmentSettings.guild_id == guild_id)
            .options(
                selectinload(RecruitmentSettings.questions),
                selectinload(RecruitmentSettings.staff_roles),
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_settings_by_id(
        session: AsyncSession, settings_id: int
    ) -> RecruitmentSettings | None:
        result = await session.execute(
            select(RecruitmentSettings)
            .where(RecruitmentSettings.id == settings_id)
            .options(
                selectinload(RecruitmentSettings.questions),
                selectinload(RecruitmentSettings.staff_roles),
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_application(
        session: AsyncSession, application_id: int
    ) -> RecruitmentApplication | None:
        return await session.get(RecruitmentApplication, application_id)

    @staticmethod
    async def active_for_user(
        session: AsyncSession, guild_id: int, user_id: int
    ) -> RecruitmentApplication | None:
        return await session.scalar(
            select(RecruitmentApplication)
            .where(
                RecruitmentApplication.guild_id == guild_id,
                RecruitmentApplication.user_id == user_id,
                RecruitmentApplication.closed_at.is_(None),
            )
            .order_by(RecruitmentApplication.id.desc())
            .limit(1)
        )

    @staticmethod
    def enabled_questions(settings: RecruitmentSettings) -> list[RecruitmentQuestion]:
        return sorted(
            (question for question in settings.questions if question.enabled),
            key=lambda row: (row.position, row.id),
        )

    @staticmethod
    def panel_embed(settings: RecruitmentSettings) -> discord.Embed:
        return discord.Embed(
            title=settings.panel_title,
            description=settings.panel_description or "Заполните заявку на вступление.",
            color=0x5865F2,
        )

    @staticmethod
    def status_label(application: RecruitmentApplication) -> str:
        labels = {
            "PENDING": "🟡 На рассмотрении",
            "ACCEPTED": "🟢 Принят",
            "REJECTED": "🔴 Отклонён",
        }
        label = labels.get(application.status, application.status)
        return f"{label} · закрыта" if application.closed_at else label

    @classmethod
    def application_embed(
        cls, application: RecruitmentApplication, guild: discord.Guild
    ) -> discord.Embed:
        member = guild.get_member(application.user_id)
        embed = discord.Embed(
            title=f"Заявка на вступление #{application.id}",
            color={"PENDING": 0xFEE75C, "ACCEPTED": 0x57F287, "REJECTED": 0xED4245}.get(
                application.status, 0x5865F2
            ),
        )
        embed.add_field(
            name="Пользователь",
            value=member.mention if member else f"<@{application.user_id}>",
            inline=True,
        )
        embed.add_field(
            name="Discord",
            value=str(member) if member else str(application.user_id),
            inline=True,
        )
        embed.add_field(name="Статус", value=cls.status_label(application), inline=False)
        for answer in application.answers[:20]:
            value = str(answer.get("value") or "—")
            embed.add_field(
                name=str(answer.get("label") or "Вопрос")[:256],
                value=value[:1024],
                inline=False,
            )
        if application.reviewer_id:
            embed.add_field(name="Решение", value=f"<@{application.reviewer_id}>", inline=True)
        if application.rejection_reason:
            embed.add_field(
                name="Причина отказа", value=application.rejection_reason[:1024], inline=False
            )
        embed.set_footer(text=f"Recruitment application ID: {application.id}")
        return embed

    @staticmethod
    def sanitize_channel_name(template: str, user: discord.abc.User, application_id: int) -> str:
        raw = template.replace("{username}", user.name).replace(
            "{application_id}", str(application_id)
        )
        cleaned = re.sub(r"[^a-z0-9а-яё-]+", "-", raw.casefold(), flags=re.IGNORECASE)
        cleaned = re.sub(r"-+", "-", cleaned).strip("-")
        return (cleaned or f"recruit-{application_id}")[:90]

    @classmethod
    async def create_application(
        cls,
        interaction: discord.Interaction,
        settings_id: int,
        answers: list[dict],
    ) -> RecruitmentApplication:
        from database.session import async_session_maker
        from modules.recruitment.views import RecruitmentTicketView

        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            raise RecruitmentError("Заявку можно создать только на сервере.")

        async with async_session_maker() as session:
            settings = await cls.get_settings_by_id(session, settings_id)
            if settings is None or settings.guild_id != guild.id or not settings.enabled:
                raise RecruitmentError("Панель вступления отключена.")
            if not settings.allow_multiple_active:
                active = await cls.active_for_user(session, guild.id, interaction.user.id)
                if active:
                    channel = f" <#{active.ticket_channel_id}>" if active.ticket_channel_id else ""
                    raise RecruitmentError(f"У вас уже есть активная заявка #{active.id}.{channel}")
            category = guild.get_channel(settings.ticket_category_id) if settings.ticket_category_id else None
            if not isinstance(category, discord.CategoryChannel):
                raise RecruitmentError("Администратор не настроил категорию recruitment tickets.")
            application = RecruitmentApplication(
                guild_id=guild.id,
                user_id=interaction.user.id,
                answers=answers,
                status="PENDING",
            )
            session.add(application)
            await session.flush()
            application_id = application.id
            staff_role_ids = [row.role_id for row in settings.staff_roles]
            channel_template = settings.channel_name_template
            await session.commit()

        overwrites: dict = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True,
                attach_files=True, embed_links=True,
            ),
        }
        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True,
                manage_messages=True, read_message_history=True,
            )
        for role_id in staff_role_ids:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True,
                )

        channel = None
        try:
            channel = await guild.create_text_channel(
                cls.sanitize_channel_name(channel_template, interaction.user, application_id),
                category=category,
                overwrites=overwrites,
                reason=f"Recruitment application #{application_id}",
            )
            async with async_session_maker() as session:
                application = await cls.get_application(session, application_id)
                application.ticket_channel_id = channel.id
                embed = cls.application_embed(application, guild)
                view = RecruitmentTicketView(application.id, guild.id)
                message = await channel.send(
                    content=interaction.user.mention,
                    embed=embed,
                    view=view,
                )
                application.ticket_message_id = message.id
                await AuditService.log(
                    session,
                    guild_id=guild.id,
                    user_id=interaction.user.id,
                    user_name=str(interaction.user),
                    action="RECRUITMENT_CREATED",
                    target_type="RECRUITMENT_APPLICATION",
                    target_id=application.id,
                    details={"channel_id": channel.id, "message_id": message.id},
                )
                await session.commit()
                logger.info(
                    "RECRUITMENT_CREATED guild=%s user=%s application=%s channel=%s message=%s",
                    guild.id, interaction.user.id, application.id, channel.id, message.id,
                )
                return application
        except Exception:
            if channel is not None:
                try:
                    await channel.delete(reason="Incomplete recruitment application rollback")
                except discord.HTTPException:
                    pass
            async with async_session_maker() as session:
                application = await cls.get_application(session, application_id)
                if application:
                    await session.delete(application)
                    await session.commit()
            raise

    @classmethod
    async def publish_panel(
        cls,
        bot: discord.Client,
        settings_id: int,
        *,
        actor: discord.abc.User | None = None,
    ) -> RecruitmentSettings:
        from database.session import async_session_maker
        from modules.recruitment.views import RecruitmentPanelView

        async with async_session_maker() as session:
            settings = await cls.get_settings_by_id(session, settings_id)
            if settings is None:
                raise RecruitmentError("Настройки вступления не найдены.")
            guild = bot.get_guild(settings.guild_id)
            channel = guild.get_channel(settings.panel_channel_id) if guild else None
            if not isinstance(channel, discord.TextChannel):
                raise RecruitmentError("Выберите текстовый канал панели.")
            if not settings.ticket_category_id:
                raise RecruitmentError("Выберите категорию recruitment tickets.")
            if not cls.enabled_questions(settings):
                raise RecruitmentError("Добавьте минимум один вопрос формы.")
            embed = cls.panel_embed(settings)
            view = RecruitmentPanelView(
                settings.id, settings.button_label, settings.button_emoji
            )
            had_message = settings.panel_message_id is not None
            message = None
            if settings.panel_message_id:
                try:
                    message = await channel.fetch_message(settings.panel_message_id)
                except discord.NotFound:
                    message = None
            if message is None:
                message = await channel.send(embed=embed, view=view)
                settings.panel_message_id = message.id
            else:
                await message.edit(embed=embed, view=view)
            if actor is not None:
                await AuditService.log(
                    session,
                    guild_id=settings.guild_id,
                    user_id=actor.id,
                    user_name=str(actor),
                    action="PANEL_UPDATED" if had_message else "PANEL_CREATED",
                    target_type="RECRUITMENT_PANEL",
                    target_id=settings.id,
                    details={
                        "channel_id": settings.panel_channel_id,
                        "message_id": settings.panel_message_id,
                    },
                )
            await session.commit()
            logger.info(
                "PANEL_UPDATED type=RECRUITMENT guild=%s settings=%s channel=%s message=%s",
                settings.guild_id, settings.id, settings.panel_channel_id,
                settings.panel_message_id,
            )
            return settings

    @classmethod
    async def review(
        cls,
        interaction: discord.Interaction,
        application_id: int,
        status: str,
        reason: str | None = None,
    ) -> RecruitmentApplication:
        from database.session import async_session_maker
        from modules.roles.service import RoleAssignmentError, RolePanelService

        if status not in {"ACCEPTED", "REJECTED"}:
            raise RecruitmentError("Недопустимый статус решения.")
        async with async_session_maker() as session:
            application = await cls.get_application(session, application_id)
            settings = await cls.get_settings(session, interaction.guild_id)
            if application is None or application.guild_id != interaction.guild_id:
                raise RecruitmentError("Заявка не найдена.")
            if application.closed_at:
                raise RecruitmentError("Заявка уже закрыта.")
            if application.status != "PENDING":
                raise RecruitmentError("По этой заявке уже принято решение.")
            if status == "ACCEPTED" and settings and settings.accepted_role_id:
                member = interaction.guild.get_member(application.user_id)
                role = interaction.guild.get_role(settings.accepted_role_id)
                if member is None or role is None:
                    raise RecruitmentError("Автор или роль после принятия не найдены.")
                try:
                    RolePanelService.validate_assignable(interaction.guild, role)
                    if role not in member.roles:
                        await member.add_roles(
                            role, reason=f"Recruitment accepted by {interaction.user}"
                        )
                except (RoleAssignmentError, discord.HTTPException) as exc:
                    raise RecruitmentError(f"Не удалось выдать роль: {exc}") from exc
            application.status = status
            application.reviewer_id = interaction.user.id
            application.rejection_reason = reason if status == "REJECTED" else None
            application.reviewed_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
            action = "RECRUITMENT_ACCEPTED" if status == "ACCEPTED" else "RECRUITMENT_REJECTED"
            await AuditService.log(
                session,
                guild_id=application.guild_id,
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action=action,
                target_type="RECRUITMENT_APPLICATION",
                target_id=application.id,
                details={"reason": reason} if reason else None,
            )
            await session.commit()
            logger.info(
                "%s guild=%s moderator=%s application=%s",
                action, application.guild_id, interaction.user.id, application.id,
            )
            return application

    @classmethod
    async def close(
        cls, interaction: discord.Interaction, application_id: int
    ) -> RecruitmentApplication:
        from database.session import async_session_maker

        async with async_session_maker() as session:
            application = await cls.get_application(session, application_id)
            if application is None or application.guild_id != interaction.guild_id:
                raise RecruitmentError("Заявка не найдена.")
            if application.status == "PENDING":
                raise RecruitmentError("Сначала примите или отклоните заявку.")
            if application.closed_at is None:
                application.closed_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
                await AuditService.log(
                    session,
                    guild_id=application.guild_id,
                    user_id=interaction.user.id,
                    user_name=str(interaction.user),
                    action="RECRUITMENT_CLOSED",
                    target_type="RECRUITMENT_APPLICATION",
                    target_id=application.id,
                )
                await session.commit()
            member = interaction.guild.get_member(application.user_id)
            if member and isinstance(interaction.channel, discord.TextChannel):
                await interaction.channel.set_permissions(
                    member,
                    view_channel=True,
                    send_messages=False,
                    read_message_history=True,
                    reason=f"Recruitment closed by {interaction.user}",
                )
                if not interaction.channel.name.startswith("closed-"):
                    await interaction.channel.edit(
                        name=f"closed-{interaction.channel.name}"[:100],
                        reason=f"Recruitment closed by {interaction.user}",
                    )
            logger.info(
                "RECRUITMENT_CLOSED guild=%s moderator=%s application=%s",
                application.guild_id, interaction.user.id, application.id,
            )
            return application

    @classmethod
    async def refresh_message(cls, bot: discord.Client, application_id: int) -> None:
        from database.session import async_session_maker
        from modules.recruitment.views import RecruitmentTicketView

        async with async_session_maker() as session:
            application = await cls.get_application(session, application_id)
            if not application or not application.ticket_channel_id or not application.ticket_message_id:
                return
            guild = bot.get_guild(application.guild_id)
            channel = guild.get_channel(application.ticket_channel_id) if guild else None
            if not isinstance(channel, discord.TextChannel):
                return
            try:
                message = await channel.fetch_message(application.ticket_message_id)
                await message.edit(
                    embed=cls.application_embed(application, guild),
                    view=RecruitmentTicketView(
                        application.id,
                        guild.id,
                        status=application.status,
                        closed=application.closed_at is not None,
                    ),
                )
            except discord.NotFound:
                logger.warning("Recruitment ticket message %s not found", application.ticket_message_id)

    @staticmethod
    async def add_question(
        session: AsyncSession,
        settings: RecruitmentSettings,
        *,
        label: str,
        placeholder: str | None,
        input_style: str,
        required: bool,
        min_length: int,
        max_length: int,
    ) -> RecruitmentQuestion:
        count = await session.scalar(
            select(func.count(RecruitmentQuestion.id)).where(
                RecruitmentQuestion.settings_id == settings.id
            )
        )
        if (count or 0) >= 20:
            raise RecruitmentError("Допускается не более 20 вопросов.")
        question = RecruitmentQuestion(
            settings_id=settings.id,
            label=label[:45],
            placeholder=(placeholder or None),
            input_style=input_style,
            required=required,
            min_length=min_length,
            max_length=max_length,
            position=(count or 0) + 1,
        )
        session.add(question)
        await session.flush()
        return question

    @staticmethod
    async def move_question(
        session: AsyncSession, question: RecruitmentQuestion, direction: int
    ) -> None:
        rows = list((await session.execute(
            select(RecruitmentQuestion)
            .where(RecruitmentQuestion.settings_id == question.settings_id)
            .order_by(RecruitmentQuestion.position, RecruitmentQuestion.id)
        )).scalars().all())
        index = next((i for i, row in enumerate(rows) if row.id == question.id), None)
        if index is None:
            return
        target = max(0, min(len(rows) - 1, index + direction))
        rows[index], rows[target] = rows[target], rows[index]
        for position, row in enumerate(rows, start=1):
            row.position = position
        await session.flush()
