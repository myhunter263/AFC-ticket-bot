import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from config import config
from integrations.backend.client import BackendClient, BackendError
from modules.orders.views import OrderPanelView, OrderActionView, order_embed

logger = logging.getLogger(__name__)


def marker_aliases(marker):
    # Recognize already-sent messages after the product rename to avoid duplicates.
    return {marker, marker.replace("Hector CRM", "AFC CRM", 1)}


class OrdersCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.client = BackendClient(config.BACKEND_URL, config.BACKEND_TOKEN)
        self.guild_id = None
        self.task = None

    async def cog_load(self):
        await self.client.start()
        self.task = asyncio.create_task(self.run(), name="crm-discord-worker")

    async def cog_unload(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await self.client.close()

    async def run(self):
        await self.bot.wait_until_ready()
        cursor = 0
        while not self.bot.is_closed():
            try:
                me = await self.client.request("GET", "/api/v1/me")
                if me["role"] != "BOT":
                    raise BackendError("Для бота нужен сервисный токен BOT")
                self.guild_id = me["guild_id"]
                self.bot.add_view(OrderPanelView(self.client, self.guild_id))
                for row in await self.client.request("GET", "/api/v1/discord/restore"):
                    if row["message_id"]:
                        self.bot.add_view(OrderActionView(self.client, row["order_id"]), message_id=row["message_id"])
                await self.drain()
                async for event in self.client.events(cursor):
                    cursor = event.get("id", cursor)
                    await self.drain()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("CRM connection interrupted: %s", type(exc).__name__)
                await asyncio.sleep(10)

    async def drain(self):
        for _ in range(100):
            jobs = await self.client.request("POST", "/api/v1/discord/jobs/claim")
            if not jobs:
                return
            job = jobs[0]
            failure = None
            try:
                await self.execute(job)
            except Exception as exc:
                failure = str(exc)[:900] if isinstance(exc, BackendError) else type(exc).__name__
                logger.warning("CRM Discord job %s failed: %s", job["id"], failure)
            await self.client.request("POST", f"/api/v1/discord/jobs/{job['id']}/complete",
                                      data={"lease": job["lease"], "error": failure})

    async def find_message(self, channel, marker):
        async for message in channel.history(limit=100):
            if message.author.id == self.bot.user.id and any(e.footer.text in marker_aliases(marker) for e in message.embeds):
                return message
        return None

    async def execute(self, job):
        settings = await self.client.request("GET", "/api/v1/discord/settings")
        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            raise BackendError("Бот не подключён к настроенному серверу")
        if job["kind"] == "panel":
            channel = guild.get_channel(settings["panel_channel_id"])
            if not isinstance(channel, discord.TextChannel):
                raise BackendError("Канал панели недоступен")
            marker = f"Hector CRM panel {guild.id}"
            message = None
            if settings["panel_message_id"]:
                try:
                    message = await channel.fetch_message(settings["panel_message_id"])
                except discord.NotFound:
                    pass
            message = message or await self.find_message(channel, marker)
            embed = discord.Embed(title=settings["panel_title"], description=settings["panel_description"], color=0x5865F2)
            embed.set_footer(text=marker)
            view = OrderPanelView(self.client, guild.id)
            if message:
                await message.edit(embed=embed, view=view)
            else:
                message = await channel.send(embed=embed, view=view)
            await self.client.request("PUT", "/api/v1/discord/messages/0", data={"kind": "panel", "channel_id": channel.id, "message_id": message.id})
            return
        order_id = job["payload"]["order_id"]
        row = await self.client.request("GET", f"/api/v1/orders/{order_id}")
        refs = await self.client.request("GET", f"/api/v1/discord/messages/{order_id}")
        if job["kind"] == "order_message":
            channel = guild.get_channel(settings["logistics_channel_id"])
            if not isinstance(channel, discord.TextChannel):
                raise BackendError("Настройте доступный канал логистов")
            marker = f"Hector CRM order {order_id}"
            ref = next((r for r in refs if r["kind"] == "logistics" and r["channel_id"] == channel.id), None)
            message = None
            if ref and ref["message_id"]:
                try:
                    message = await channel.fetch_message(ref["message_id"])
                except discord.NotFound:
                    pass
            message = message or await self.find_message(channel, marker)
            embed = order_embed(row)
            embed.set_footer(text=marker)
            view = OrderActionView(self.client, order_id)
            if message:
                await message.edit(embed=embed, view=view)
            else:
                message = await channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
            await self.client.request("PUT", f"/api/v1/discord/messages/{order_id}", data={"kind": "logistics", "channel_id": channel.id, "message_id": message.id})
            return
        if job["kind"] != "customer_notice":
            raise BackendError("Неизвестное задание")
        user = self.bot.get_user(row["discord_user_id"]) or await self.bot.fetch_user(row["discord_user_id"])
        marker = f"Hector CRM notification {job['id']}"
        # Preserve the status that caused this notification, even after an outage.
        from services.orders.domain import LABELS, Status
        row = {**row, "status": job["payload"]["status"],
               "status_label": LABELS[Status(job["payload"]["status"])],
               "assigned_user_id": job["payload"].get("assigned_user_id", row["assigned_user_id"])}
        embed = order_embed(row)
        embed.set_footer(text=marker)
        try:
            dm = user.dm_channel or await user.create_dm()
            if not await self.find_message(dm, marker):
                await dm.send(embed=embed)
            return
        except discord.Forbidden:
            pass
        ref = next((r for r in refs if r["kind"] == "fallback"), None)
        channel = guild.get_channel(ref["channel_id"]) if ref else None
        if channel is None:
            category = guild.get_channel(settings["fallback_category_id"])
            if not isinstance(category, discord.CategoryChannel):
                raise BackendError("DM закрыты; настройте категорию приватных уведомлений")
            name = f"order-{order_id}"
            topic = f"Hector CRM private order {order_id} customer {user.id}"
            channel = next((c for c in category.text_channels if c.topic in marker_aliases(topic)), None)
            if channel is None:
                member = guild.get_member(user.id) or await guild.fetch_member(user.id)
                channel = await guild.create_text_channel(name, category=category, topic=topic, overwrites={
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
                    guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
                })
            await self.client.request("PUT", f"/api/v1/discord/messages/{order_id}", data={"kind": "fallback", "channel_id": channel.id})
        # Reconcile access even when an existing channel's overwrites were changed.
        member = guild.get_member(user.id) or await guild.fetch_member(user.id)
        await channel.edit(topic=f"Hector CRM private order {order_id} customer {user.id}", overwrites={
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        })
        if not await self.find_message(channel, marker):
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="orders-panel", description="Создать или обновить панель логистических заказов")
    @app_commands.guild_only()
    async def panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if interaction.guild_id != self.guild_id:
            return await interaction.followup.send("Backend этого сервера не подключён", ephemeral=True)
        try:
            await self.client.request("POST", "/api/v1/discord/panel", member=interaction.user)
            await interaction.followup.send("Публикация панели поставлена в очередь", ephemeral=True)
        except BackendError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)


async def setup(bot):
    if config.BACKEND_URL and config.BACKEND_TOKEN:
        await bot.add_cog(OrdersCog(bot))
