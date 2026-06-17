from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Coroutine, Any

import discord

logger = logging.getLogger(__name__)


class TicketCreateModal(discord.ui.Modal):

    def __init__(
        self,
        panel_name: str,
        fields: list[dict],
        on_submit_callback: Callable[..., Coroutine[Any, Any, None]],
    ) -> None:
        super().__init__(title=panel_name[:45])
        self._fields_meta = fields
        self._callback = on_submit_callback

        for field in fields[:5]:
            style = (
                discord.TextStyle.long
                if field.get("field_type") in ("long_text",)
                else discord.TextStyle.short
            )
            item = discord.ui.TextInput(
                label=field["label"][:45],
                placeholder=field.get("placeholder") or "",
                required=field.get("is_required", True),
                min_length=field.get("min_length") or 0,
                max_length=field.get("max_length") or 1024,
                style=style,
            )
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        responses = []
        for i, field_meta in enumerate(self._fields_meta[:5]):
            item: discord.ui.TextInput = self.children[i]  # type: ignore
            responses.append(
                {
                    "field_id": field_meta.get("id"),
                    "field_label": field_meta["label"],
                    "value": item.value,
                }
            )
        await self._callback(interaction, responses)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.exception("Error in TicketCreateModal: %s", error)
        try:
            embed = discord.Embed(
                title="❌ Ошибка",
                description="Не удалось создать заявку. Попробуйте снова.",
                color=0xED4245,
            )
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception:
            pass
