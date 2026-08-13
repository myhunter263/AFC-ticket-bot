from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from database.session import async_session_maker
from services.audit_service import AuditService
from services.points_service import PointsService
from utils.embeds import EmbedBuilder
from utils.permissions import PermissionChecker

logger = logging.getLogger(__name__)


class PointsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="afc-points", description="[AFC] Показать баллы пользователя")
    @app_commands.guild_only()
    @app_commands.describe(member="Пользователь (по умолчанию — вы)")
    async def show_points(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        target = member or interaction.user
        async with async_session_maker() as session:
            points = await PointsService.get_points(session, interaction.guild_id, target.id)
            entry = await PointsService.get_or_create(session, interaction.guild_id, target.id)
            total_earned = entry.total_earned

        embed = discord.Embed(
            title=f"⭐ Баллы — {target.display_name}",
            color=0xFEE75C,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Текущий баланс", value=f"**{points}** баллов", inline=True)
        embed.add_field(name="Всего заработано", value=f"**{total_earned}** баллов", inline=True)
        embed.set_footer(text=f"Сервер: {interaction.guild.name}")
        embed.timestamp = __import__("datetime").datetime.utcnow()
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="afc-points-top", description="[AFC] Топ-10 участников по баллам")
    @app_commands.guild_only()
    async def points_top(self, interaction: discord.Interaction) -> None:
        async with async_session_maker() as session:
            leaders = await PointsService.get_leaderboard(session, interaction.guild_id, limit=10)

        embed = discord.Embed(
            title="🏆 Топ участников по баллам",
            color=0xFEE75C,
        )
        if not leaders:
            embed.description = "Пока никто не заработал баллы."
        else:
            medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
            lines = []
            for i, entry in enumerate(leaders):
                member = interaction.guild.get_member(entry.user_id)
                name = member.display_name if member else f"<@{entry.user_id}>"
                lines.append(f"{medals[i]} **{name}** — {entry.points} баллов")
            embed.description = "\n".join(lines)

        embed.set_footer(text=f"Сервер: {interaction.guild.name}")
        embed.timestamp = __import__("datetime").datetime.utcnow()
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="afc-points-set", description="[AFC] Установить баллы пользователю (Admin)")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(member="Пользователь", amount="Новое количество баллов")
    async def points_set(self, interaction: discord.Interaction, member: discord.Member, amount: int) -> None:
        if not PermissionChecker.is_discord_admin(interaction):
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "Нет доступа",
                    "Только администраторы Discord-сервера могут устанавливать баллы.",
                ),
                ephemeral=True,
            )
            return

        async with async_session_maker() as session:
            await PointsService.set_points(session, interaction.guild_id, member.id, amount)
            await session.commit()

        embed = EmbedBuilder.success(
            "Баллы установлены",
            f"{member.mention}: баланс установлен на **{amount}** баллов.",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="afc-points-add", description="[AFC] Начислить/списать баллы (Admin)")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(member="Пользователь", amount="Баллы (отрицательное значение — списание)")
    async def points_add(self, interaction: discord.Interaction, member: discord.Member, amount: int) -> None:
        if not PermissionChecker.is_discord_admin(interaction):
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "Нет доступа",
                    "Только администраторы Discord-сервера могут редактировать баллы этой командой.",
                ),
                ephemeral=True,
            )
            return

        async with async_session_maker() as session:
            entry = await PointsService.award(session, interaction.guild_id, member.id, amount)
            await session.commit()
            new_total = entry.points

        sign = "+" if amount >= 0 else ""
        embed = EmbedBuilder.success(
            "Баллы обновлены",
            f"{member.mention}: **{sign}{amount}** баллов. Итого: **{new_total}**.",
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="afc-points-reset-all",
        description="[AFC] Удалить все баллы на сервере (Discord Admin)",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def points_reset_all(self, interaction: discord.Interaction) -> None:
        if not PermissionChecker.is_discord_admin(interaction):
            await interaction.response.send_message(
                embed=EmbedBuilder.error(
                    "Нет доступа",
                    "Только администраторы Discord-сервера могут удалить все баллы.",
                ),
                ephemeral=True,
            )
            return

        view = ResetAllPointsView(interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(
            embed=EmbedBuilder.warning(
                "Удалить все баллы?",
                "Будут удалены балансы и история заработанных баллов всех участников этого сервера. "
                "Действие необратимо.",
            ),
            view=view,
            ephemeral=True,
        )


class ResetAllPointsView(discord.ui.View):
    def __init__(self, guild_id: int, requested_by: int) -> None:
        super().__init__(timeout=60)
        self.guild_id = guild_id
        self.requested_by = requested_by

    @discord.ui.button(label="Удалить все баллы", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if (
            interaction.user.id != self.requested_by
            or not PermissionChecker.is_discord_admin(interaction)
        ):
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Нет доступа", "Подтвердить удаление может только вызвавший команду администратор."),
                ephemeral=True,
            )
            return

        async with async_session_maker() as session:
            deleted_count = await PointsService.delete_all(session, self.guild_id)
            await AuditService.log(
                session,
                guild_id=self.guild_id,
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action="reset_all_points",
                target_type="guild",
                target_id=self.guild_id,
                details={"deleted_users": deleted_count},
            )
            await session.commit()

        await interaction.response.edit_message(
            embed=EmbedBuilder.success(
                "Баллы удалены",
                f"Удалены данные о баллах для **{deleted_count}** участников.",
            ),
            view=None,
        )

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.requested_by:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Нет доступа"),
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            embed=EmbedBuilder.info("Отменено", "Баллы не изменены."),
            view=None,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PointsCog(bot))
