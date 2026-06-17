from __future__ import annotations

import asyncio
import logging

import discord

logger = logging.getLogger(__name__)


async def _bg_delete(interaction: discord.Interaction, delay: float, msg: discord.Message | None) -> None:
    await asyncio.sleep(delay)
    try:
        if msg:
            await msg.delete()
        else:
            await interaction.delete_original_response()
    except (discord.NotFound, discord.HTTPException, discord.Forbidden):
        pass


def schedule_delete(
    interaction: discord.Interaction,
    delay: float = 7.0,
    msg: discord.Message | None = None,
) -> None:
    """Schedule deletion of an ephemeral response in the background."""
    asyncio.create_task(_bg_delete(interaction, delay, msg))


async def respond_and_delete(
    interaction: discord.Interaction,
    embed: discord.Embed,
    delay: float = 7.0,
    ephemeral: bool = True,
) -> None:
    """Send ephemeral response and auto-delete it after `delay` seconds."""
    if interaction.response.is_done():
        msg = await interaction.followup.send(embed=embed, ephemeral=ephemeral, wait=True)
        schedule_delete(interaction, delay=delay, msg=msg)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
        schedule_delete(interaction, delay=delay)
