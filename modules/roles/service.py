from __future__ import annotations

import logging

import discord
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import RolePanel, RolePanelItem
from services.audit_service import AuditService

logger = logging.getLogger(__name__)


class RoleAssignmentError(ValueError):
    pass


class RolePanelService:
    DANGEROUS_PERMISSIONS = {
        "administrator": "Administrator",
        "manage_guild": "Manage Server",
        "manage_roles": "Manage Roles",
        "manage_channels": "Manage Channels",
        "ban_members": "Ban Members",
        "kick_members": "Kick Members",
    }

    @staticmethod
    async def list_panels(session: AsyncSession, guild_id: int) -> list[RolePanel]:
        result = await session.execute(
            select(RolePanel)
            .where(RolePanel.guild_id == guild_id)
            .options(selectinload(RolePanel.items))
            .order_by(RolePanel.id)
        )
        return list(result.scalars().unique().all())

    @staticmethod
    async def get_panel(session: AsyncSession, panel_id: int) -> RolePanel | None:
        result = await session.execute(
            select(RolePanel)
            .where(RolePanel.id == panel_id)
            .options(selectinload(RolePanel.items))
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_item(session: AsyncSession, item_id: int) -> RolePanelItem | None:
        result = await session.execute(
            select(RolePanelItem)
            .where(RolePanelItem.id == item_id)
            .options(selectinload(RolePanelItem.panel))
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create_panel(
        session: AsyncSession,
        *,
        guild_id: int,
        channel_id: int,
        title: str,
        description: str | None,
        color: int,
        created_by: int,
    ) -> RolePanel:
        panel = RolePanel(
            guild_id=guild_id,
            panel_channel_id=channel_id,
            title=title,
            description=description,
            color=color,
            created_by=created_by,
        )
        session.add(panel)
        await session.flush()
        return panel

    @classmethod
    def validate_assignable(cls, guild: discord.Guild, role: discord.Role) -> None:
        bot_member = guild.me
        if role.guild.id != guild.id or guild.get_role(role.id) is None:
            raise RoleAssignmentError("Роль не существует на этом сервере.")
        if role.is_default():
            raise RoleAssignmentError("Роль @everyone нельзя выдавать через панель.")
        if role.managed:
            raise RoleAssignmentError("Эта роль управляется интеграцией Discord.")
        if bot_member is None or not bot_member.guild_permissions.manage_roles:
            raise RoleAssignmentError("У бота отсутствует разрешение Manage Roles.")
        if role >= bot_member.top_role:
            raise RoleAssignmentError("Роль бота должна находиться выше выдаваемой роли.")
        dangerous = [
            label
            for attr, label in cls.DANGEROUS_PERMISSIONS.items()
            if getattr(role.permissions, attr, False)
        ]
        if dangerous:
            raise RoleAssignmentError(
                "Self-role содержит опасные права: " + ", ".join(dangerous) + "."
            )

    @staticmethod
    async def add_item(
        session: AsyncSession,
        panel: RolePanel,
        role: discord.Role,
        *,
        label: str | None = None,
        emoji: str | None = None,
    ) -> RolePanelItem:
        item_count = await session.scalar(
            select(func.count(RolePanelItem.id)).where(RolePanelItem.panel_id == panel.id)
        )
        if (item_count or 0) >= 25:
            raise RoleAssignmentError("В одной панели Discord может быть не более 25 ролей.")
        existing = await session.scalar(
            select(RolePanelItem).where(
                RolePanelItem.panel_id == panel.id,
                RolePanelItem.role_id == role.id,
            )
        )
        if existing:
            raise RoleAssignmentError("Эта роль уже добавлена в панель.")
        max_position = await session.scalar(
            select(func.max(RolePanelItem.position)).where(RolePanelItem.panel_id == panel.id)
        )
        item = RolePanelItem(
            panel_id=panel.id,
            role_id=role.id,
            label=(label or role.name)[:80],
            emoji=emoji or None,
            position=(max_position or 0) + 1,
            rules={},
        )
        session.add(item)
        await session.flush()
        return item

    @staticmethod
    async def replace_item_role(
        session: AsyncSession,
        item: RolePanelItem,
        role: discord.Role,
    ) -> None:
        duplicate = await session.scalar(
            select(RolePanelItem).where(
                RolePanelItem.panel_id == item.panel_id,
                RolePanelItem.role_id == role.id,
                RolePanelItem.id != item.id,
            )
        )
        if duplicate:
            raise RoleAssignmentError("Эта роль уже есть в панели.")
        item.role_id = role.id
        await session.flush()

    @staticmethod
    async def remove_item(session: AsyncSession, item: RolePanelItem) -> None:
        await session.delete(item)
        await session.flush()

    @staticmethod
    async def move_item(session: AsyncSession, item: RolePanelItem, direction: int) -> None:
        ordered = list((await session.execute(
            select(RolePanelItem)
            .where(RolePanelItem.panel_id == item.panel_id)
            .order_by(RolePanelItem.position, RolePanelItem.id)
        )).scalars().all())
        index = next((i for i, row in enumerate(ordered) if row.id == item.id), None)
        if index is None:
            return
        target_index = max(0, min(len(ordered) - 1, index + direction))
        if target_index == index:
            return
        ordered[index], ordered[target_index] = ordered[target_index], ordered[index]
        for position, row in enumerate(ordered, start=1):
            row.position = position
        await session.flush()

    @staticmethod
    def embed(panel: RolePanel) -> discord.Embed:
        return discord.Embed(
            title=panel.title,
            description=panel.description or "Нажмите кнопку, чтобы получить или снять роль.",
            color=panel.color,
        )

    @staticmethod
    async def toggle_role(member: discord.Member, role: discord.Role) -> bool:
        if role in member.roles:
            await member.remove_roles(role, reason="Self-role panel")
            return False
        await member.add_roles(role, reason="Self-role panel")
        return True

    @classmethod
    async def publish(
        cls,
        bot: discord.Client,
        panel_id: int,
        *,
        actor: discord.abc.User | None = None,
    ) -> RolePanel:
        from database.session import async_session_maker
        from modules.roles.views import RolePanelView

        async with async_session_maker() as session:
            panel = await cls.get_panel(session, panel_id)
            if panel is None:
                raise RoleAssignmentError("Панель ролей не найдена.")
            guild = bot.get_guild(panel.guild_id)
            if guild is None:
                raise RoleAssignmentError("Сервер недоступен боту.")
            channel = guild.get_channel(panel.panel_channel_id)
            if not isinstance(channel, discord.TextChannel):
                raise RoleAssignmentError("Канал панели не найден или не является текстовым.")
            for item in panel.items:
                role = guild.get_role(item.role_id)
                if item.enabled and role is not None:
                    cls.validate_assignable(guild, role)
            embed = cls.embed(panel)
            view = RolePanelView(panel.id, panel.items)
            message = None
            if panel.panel_message_id:
                try:
                    message = await channel.fetch_message(panel.panel_message_id)
                except discord.NotFound:
                    message = None
            if message is None:
                message = await channel.send(embed=embed, view=view)
                panel.panel_message_id = message.id
            else:
                await message.edit(embed=embed, view=view)
            if actor is not None:
                await AuditService.log(
                    session,
                    guild_id=panel.guild_id,
                    user_id=actor.id,
                    user_name=str(actor),
                    action="PANEL_UPDATED",
                    target_type="ROLE_PANEL",
                    target_id=panel.id,
                    details={
                        "channel_id": panel.panel_channel_id,
                        "message_id": panel.panel_message_id,
                    },
                )
            await session.commit()
            logger.info(
                "PANEL_UPDATED type=ROLE guild=%s panel=%s channel=%s message=%s",
                panel.guild_id, panel.id, panel.panel_channel_id, panel.panel_message_id,
            )
            return panel

    @classmethod
    async def delete_panel(
        cls,
        session: AsyncSession,
        bot: discord.Client,
        panel: RolePanel,
        moderator: discord.abc.User,
    ) -> None:
        guild = bot.get_guild(panel.guild_id)
        channel = guild.get_channel(panel.panel_channel_id) if guild else None
        if isinstance(channel, discord.TextChannel) and panel.panel_message_id:
            try:
                message = await channel.fetch_message(panel.panel_message_id)
                await message.delete(reason=f"Role panel deleted by {moderator}")
            except (discord.NotFound, discord.HTTPException):
                pass
        await AuditService.log(
            session,
            guild_id=panel.guild_id,
            user_id=moderator.id,
            user_name=str(moderator),
            action="PANEL_DELETED",
            target_type="ROLE_PANEL",
            target_id=panel.id,
        )
        await session.delete(panel)
        await session.flush()
