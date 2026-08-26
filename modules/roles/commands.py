from __future__ import annotations

from discord.ext import commands


class RolesModule(commands.Cog):
    """Self-role module; configuration is exposed through the shared admin UI."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RolesModule(bot))
