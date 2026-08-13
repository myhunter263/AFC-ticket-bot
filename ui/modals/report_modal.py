from __future__ import annotations

import logging
from typing import Callable, Coroutine, Any

import discord

logger = logging.getLogger(__name__)


class ReportModal(discord.ui.Modal, title="Отчёт о выполнении"):
    content = discord.ui.TextInput(
        label="Описание выполненной работы",
        style=discord.TextStyle.long,
        placeholder="Опишите что было сделано...",
        required=True,
        min_length=10,
        max_length=1000,
    )

    def __init__(self, on_submit: Callable[..., Coroutine[Any, Any, None]]) -> None:
        super().__init__()
        self._callback = on_submit

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._callback(interaction, self.content.value)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.exception("Error in ReportModal: %s", error)
        try:
            await interaction.response.send_message(
                embed=discord.Embed(title="❌ Ошибка", description="Не удалось сохранить отчёт.", color=0xED4245),
                ephemeral=True,
            )
        except Exception:
            pass
