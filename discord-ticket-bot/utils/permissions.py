from __future__ import annotations

from typing import Optional

import discord
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import StaffRole


class PermissionChecker:

    @staticmethod
    async def is_bot_admin(
        interaction: discord.Interaction,
        session: AsyncSession,
    ) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        result = await session.execute(
            select(StaffRole).where(
                StaffRole.guild_id == interaction.guild_id,
                StaffRole.role_type == "admin",
                StaffRole.panel_id.is_(None),
            )
        )
        admin_roles = result.scalars().all()
        user_role_ids = {r.id for r in interaction.user.roles}
        return any(sr.role_id in user_role_ids for sr in admin_roles)

    @staticmethod
    async def is_staff(
        interaction: discord.Interaction,
        session: AsyncSession,
        panel_id: Optional[int] = None,
    ) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True

        query = select(StaffRole).where(
            StaffRole.guild_id == interaction.guild_id,
        )
        result = await session.execute(query)
        all_roles = result.scalars().all()

        user_role_ids = {r.id for r in interaction.user.roles}

        for sr in all_roles:
            if sr.role_id not in user_role_ids:
                continue
            if sr.panel_id is None:
                return True
            if panel_id is not None and sr.panel_id == panel_id:
                return True

        return False

    @staticmethod
    async def can_manage_ticket(
        interaction: discord.Interaction,
        session: AsyncSession,
        ticket,
    ) -> bool:
        if interaction.user.id == ticket.author_id:
            return True
        return await PermissionChecker.is_staff(interaction, session, ticket.panel_id)
