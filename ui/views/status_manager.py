from __future__ import annotations

import discord

from database.session import async_session_maker
from services.audit_service import AuditService
from services.status_service import StatusService
from ui.modals.status_modal import StatusCreateModal, StatusEditModal
from utils.embeds import EmbedBuilder
from utils.permissions import PermissionChecker


class StatusListView(discord.ui.View):
    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=300)
        self.guild_id = guild_id

    @discord.ui.button(label="Создать статус", style=discord.ButtonStyle.success, emoji="➕", row=0)
    async def create_status(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            if not await PermissionChecker.is_bot_admin(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа", "Только администраторы могут управлять статусами."),
                    ephemeral=True,
                )
                return

        async def on_submit(inter: discord.Interaction, **kwargs) -> None:
            async with async_session_maker() as session:
                status = await StatusService.create(session, self.guild_id, **kwargs)
                await AuditService.log(
                    session,
                    guild_id=self.guild_id,
                    user_id=inter.user.id,
                    user_name=str(inter.user),
                    action="create_status",
                    target_type="status",
                    target_id=status.id,
                    details={"name": status.name},
                )
                await session.commit()
            embed = EmbedBuilder.success("Статус создан", f"Статус **{status.name}** успешно создан.")
            await inter.response.send_message(embed=embed, ephemeral=True)
            await self._refresh(interaction)

        modal = StatusCreateModal(on_submit)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Список статусов", style=discord.ButtonStyle.primary, emoji="📋", row=0)
    async def list_statuses(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            statuses = await StatusService.get_all(session, self.guild_id)

        if not statuses:
            await interaction.response.send_message(
                embed=EmbedBuilder.info("Статусы", "Статусы не созданы. Нажмите «Создать статус»."),
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="🏷️ Статусы тикетов", color=0x5865F2)
        for s in statuses:
            flags = []
            if s.is_default:
                flags.append("По умолчанию")
            if s.is_closed:
                flags.append("Закрывает тикет")
            emoji_str = s.emoji or ""
            flags_str = f" ({', '.join(flags)})" if flags else ""
            embed.add_field(
                name=f"{emoji_str} {s.name}{flags_str}",
                value=f"Цвет: `#{s.color:06X}` | ID: `{s.id}`",
                inline=False,
            )

        view = StatusManageView(self.guild_id, statuses)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def _refresh(self, interaction: discord.Interaction) -> None:
        async with async_session_maker() as session:
            statuses = await StatusService.get_all(session, self.guild_id)

        embed = discord.Embed(title="🏷️ Управление статусами", color=0x5865F2)
        embed.description = f"Всего статусов: **{len(statuses)}**"
        try:
            await interaction.edit_original_response(embed=embed, view=self)
        except discord.HTTPException:
            pass


class StatusManageView(discord.ui.View):
    def __init__(self, guild_id: int, statuses: list) -> None:
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.statuses = statuses

        options = [
            discord.SelectOption(
                label=s.name[:100],
                value=str(s.id),
                emoji=s.emoji or None,
                description=f"#{s.color:06X}" + (" • По умолчанию" if s.is_default else ""),
            )
            for s in statuses[:25]
        ]

        self.edit_select = discord.ui.Select(
            placeholder="Выберите статус для изменения...",
            options=options,
            custom_id="status_edit_select",
        )
        self.edit_select.callback = self._edit_callback
        self.add_item(self.edit_select)

        self.delete_select = discord.ui.Select(
            placeholder="Выберите статус для удаления...",
            options=options,
            custom_id="status_delete_select",
        )
        self.delete_select.callback = self._delete_callback
        self.add_item(self.delete_select)

    async def _edit_callback(self, interaction: discord.Interaction) -> None:
        status_id = int(self.edit_select.values[0])

        async with async_session_maker() as session:
            if not await PermissionChecker.is_bot_admin(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
                )
                return
            status = await StatusService.get_by_id(session, status_id)
            if not status:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Статус не найден."), ephemeral=True
                )
                return

        async def on_submit(inter: discord.Interaction, **kwargs) -> None:
            async with async_session_maker() as session:
                s = await StatusService.get_by_id(session, status_id)
                if s:
                    await StatusService.update(session, s, **kwargs)
                    await AuditService.log(
                        session,
                        guild_id=self.guild_id,
                        user_id=inter.user.id,
                        user_name=str(inter.user),
                        action="update_status",
                        target_type="status",
                        target_id=status_id,
                    )
                    await session.commit()
            await inter.response.send_message(
                embed=EmbedBuilder.success("Статус обновлён"), ephemeral=True
            )

        modal = StatusEditModal(
            on_submit,
            current_name=status.name,
            current_emoji=status.emoji,
            current_color=status.color,
            current_is_closed=status.is_closed,
            current_is_default=status.is_default,
        )
        await interaction.response.send_modal(modal)

    async def _delete_callback(self, interaction: discord.Interaction) -> None:
        status_id = int(self.delete_select.values[0])

        async with async_session_maker() as session:
            if not await PermissionChecker.is_bot_admin(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
                )
                return
            status = await StatusService.get_by_id(session, status_id)
            if not status:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Статус не найден."), ephemeral=True
                )
                return
            name = status.name
            await StatusService.delete(session, status)
            await AuditService.log(
                session,
                guild_id=self.guild_id,
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action="delete_status",
                target_type="status",
                target_id=status_id,
                details={"name": name},
            )
            await session.commit()

        await interaction.response.send_message(
            embed=EmbedBuilder.success("Статус удалён", f"Статус **{name}** удалён."),
            ephemeral=True,
        )
