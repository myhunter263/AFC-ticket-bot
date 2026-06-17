from __future__ import annotations

import logging
import traceback

import discord
from discord import app_commands
from discord.ext import commands

from config import config

logger = logging.getLogger(__name__)


async def _send_error(interaction: discord.Interaction, message: str) -> None:
    embed = discord.Embed(
        title="❌ Ошибка",
        description=message,
        color=config.COLOR_ERROR,
    )
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except discord.HTTPException:
        pass


def setup_error_handler(bot: commands.Bot) -> None:

    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.CommandNotFound):
            await _send_error(interaction, "Команда не найдена.")
            return

        if isinstance(error, app_commands.MissingPermissions):
            await _send_error(interaction, "У вас недостаточно прав для выполнения этой команды.")
            return

        if isinstance(error, app_commands.BotMissingPermissions):
            await _send_error(
                interaction,
                f"У бота недостаточно прав: `{', '.join(error.missing_permissions)}`",
            )
            return

        if isinstance(error, app_commands.CommandOnCooldown):
            await _send_error(
                interaction,
                f"Команда на перезарядке. Попробуйте снова через {error.retry_after:.1f}с.",
            )
            return

        if isinstance(error, app_commands.CheckFailure):
            await _send_error(interaction, "У вас нет доступа к этой команде.")
            return

        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        logger.error("Unhandled app command error in %s:\n%s", interaction.command, tb)

        await _send_error(
            interaction,
            "Произошла непредвиденная ошибка. Администраторы уведомлены.",
        )

    @bot.event
    async def on_error(event: str, *args, **kwargs) -> None:
        logger.exception("Unhandled exception in event '%s'", event)
