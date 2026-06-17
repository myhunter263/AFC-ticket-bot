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


class AwardPointsModal(discord.ui.Modal, title="Начислить баллы"):
    amount = discord.ui.TextInput(
        label="Количество баллов",
        style=discord.TextStyle.short,
        placeholder="Например: 50",
        required=True,
        min_length=1,
        max_length=6,
    )
    reason = discord.ui.TextInput(
        label="Причина (необязательно)",
        style=discord.TextStyle.short,
        placeholder="За что начисляем баллы?",
        required=False,
        max_length=200,
    )

    def __init__(self, target_user: discord.Member, on_submit: Callable[..., Coroutine[Any, Any, None]]) -> None:
        super().__init__()
        self.target_user = target_user
        self._callback = on_submit

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            amt = int(self.amount.value.strip())
        except ValueError:
            await interaction.response.send_message(
                embed=discord.Embed(title="❌ Ошибка", description="Введите целое число баллов.", color=0xED4245),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        await self._callback(interaction, self.target_user, amt, self.reason.value or "")

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.exception("Error in AwardPointsModal: %s", error)
        try:
            embed = discord.Embed(title="❌ Ошибка", description="Не удалось начислить баллы. Попробуйте ещё раз.", color=0xED4245)
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception:
            pass
