from __future__ import annotations

import logging

import discord

from database.session import async_session_maker
from modules.roles.service import RoleAssignmentError, RolePanelService
from services.audit_service import AuditService
from utils.embeds import EmbedBuilder

logger = logging.getLogger(__name__)


class RolePanelView(discord.ui.View):
    message_type = "PERMANENT_ROLE_PANEL"

    def __init__(self, panel_id: int, items: list | None = None) -> None:
        super().__init__(timeout=None)
        self.panel_id = panel_id
        for button_index, item in enumerate(
            sorted(items or [], key=lambda row: (row.position, row.id))[:25]
        ):
            if not item.enabled:
                continue
            button = discord.ui.Button(
                label=item.label[:80],
                emoji=item.emoji or None,
                style=discord.ButtonStyle.secondary,
                custom_id=f"role_panel:{panel_id}:item:{item.id}",
                row=button_index // 5,
            )
            button.callback = self._make_callback(item.id)
            self.add_item(button)

    def _make_callback(self, item_id: int):
        async def callback(interaction: discord.Interaction) -> None:
            if not isinstance(interaction.user, discord.Member) or interaction.guild is None:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Недоступно", "Панель работает только на сервере."),
                    ephemeral=True,
                )
                return
            async with async_session_maker() as session:
                item = await RolePanelService.get_item(session, item_id)
                if (
                    item is None
                    or item.panel_id != self.panel_id
                    or not item.enabled
                    or not item.panel.enabled
                    or item.panel.guild_id != interaction.guild_id
                ):
                    await interaction.response.send_message(
                        embed=EmbedBuilder.error("Роль недоступна", "Настройка панели изменилась."),
                        ephemeral=True,
                    )
                    return
                role = interaction.guild.get_role(item.role_id)
                if role is None:
                    await interaction.response.send_message(
                        embed=EmbedBuilder.error("Роль не найдена"), ephemeral=True
                    )
                    return
                try:
                    RolePanelService.validate_assignable(interaction.guild, role)
                    granted = await RolePanelService.toggle_role(interaction.user, role)
                except (RoleAssignmentError, discord.Forbidden, discord.HTTPException) as exc:
                    await interaction.response.send_message(
                        embed=EmbedBuilder.error("Не удалось изменить роль", str(exc)),
                        ephemeral=True,
                    )
                    return
                action = "ROLE_GRANTED" if granted else "ROLE_REMOVED"
                await AuditService.log(
                    session,
                    guild_id=interaction.guild_id,
                    user_id=interaction.user.id,
                    user_name=str(interaction.user),
                    action=action,
                    target_type="ROLE",
                    target_id=role.id,
                    details={"panel_id": self.panel_id},
                )
                await session.commit()
            logger.info(
                "%s guild=%s user=%s role=%s panel=%s",
                action, interaction.guild_id, interaction.user.id, role.id, self.panel_id,
            )
            verb = "выдана" if granted else "снята"
            await interaction.response.send_message(
                embed=EmbedBuilder.success("Роль обновлена", f"Роль «{role.name}» {verb}."),
                ephemeral=True,
            )

        return callback
