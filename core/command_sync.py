from __future__ import annotations

import discord
from discord.ext import commands


async def sync_commands_to_guild(
    bot: commands.Bot,
    guild: discord.abc.Snowflake | int,
) -> list:
    """Copy every global app command and publish it to one guild immediately."""
    guild_id = guild if isinstance(guild, int) else guild.id
    target = discord.Object(id=guild_id)
    bot.tree.copy_global_to(guild=target)
    return await bot.tree.sync(guild=target)
