from __future__ import annotations

import asyncio
import logging
import sys

import discord
from discord.ext import commands

from config import config
from database.session import init_db
from utils.error_handler import setup_error_handler

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

COGS = [
    "cogs.setup",
    "cogs.admin",
    "cogs.tickets",
    "cogs.points",
]


class TicketBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True

        super().__init__(
            command_prefix=config.BOT_PREFIX,
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self) -> None:
        logger.info("Initializing database...")
        await init_db()

        logger.info("Loading cogs...")
        for cog in COGS:
            try:
                await self.load_extension(cog)
                logger.info("Loaded cog: %s", cog)
            except Exception as exc:
                logger.error("Failed to load cog %s: %s", cog, exc, exc_info=True)

        if config.DISCORD_GUILD_ID:
            guild = discord.Object(id=config.DISCORD_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info("Synced %d commands to guild %d", len(synced), config.DISCORD_GUILD_ID)
        else:
            synced = await self.tree.sync()
            logger.info("Synced %d global commands", len(synced))

        setup_error_handler(self)
        logger.info("Bot setup complete.")

    async def on_ready(self) -> None:
        logger.info(
            "Bot is ready! Logged in as %s (ID: %d) on %d guild(s).",
            self.user,
            self.user.id,
            len(self.guilds),
        )
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="заявки | /admin",
            )
        )

    async def on_guild_join(self, guild: discord.Guild) -> None:
        from database.session import async_session_maker
        from services.ticket_service import TicketService
        from services.status_service import StatusService

        async with async_session_maker() as session:
            await TicketService.get_or_create_guild(session, guild)
            await StatusService.ensure_defaults(session, guild.id)
            await session.commit()

        logger.info("Joined guild: %s (ID: %d)", guild.name, guild.id)

    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        from database.session import async_session_maker
        from services.ticket_service import TicketService

        if not isinstance(channel, discord.TextChannel):
            return

        async with async_session_maker() as session:
            ticket = await TicketService.get_by_channel(session, channel.id)
            if ticket and not ticket.is_closed:
                from services.status_service import StatusService
                from sqlalchemy import select
                from database.models import TicketStatus

                result = await session.execute(
                    select(TicketStatus).where(
                        TicketStatus.guild_id == ticket.guild_id,
                        TicketStatus.is_closed == True,
                    ).order_by(TicketStatus.order).limit(1)
                )
                closed_status = result.scalar_one_or_none()
                await TicketService.close(session, ticket, self.user.id, closed_status)
                await session.commit()
                logger.info("Auto-closed ticket #%d (channel deleted)", ticket.number)


async def main() -> None:
    bot = TicketBot()
    async with bot:
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
