from __future__ import annotations

import datetime
from typing import Optional

import discord

from config import config


class EmbedBuilder:

    @staticmethod
    def base(
        title: str,
        description: str = "",
        color: int = config.COLOR_PRIMARY,
    ) -> discord.Embed:
        embed = discord.Embed(title=title, description=description, color=color)
        embed.timestamp = datetime.datetime.utcnow()
        return embed

    @staticmethod
    def success(title: str, description: str = "") -> discord.Embed:
        embed = discord.Embed(title=f"✅ {title}", description=description, color=config.COLOR_SUCCESS)
        embed.timestamp = datetime.datetime.utcnow()
        return embed

    @staticmethod
    def error(title: str, description: str = "") -> discord.Embed:
        embed = discord.Embed(title=f"❌ {title}", description=description, color=config.COLOR_ERROR)
        embed.timestamp = datetime.datetime.utcnow()
        return embed

    @staticmethod
    def warning(title: str, description: str = "") -> discord.Embed:
        embed = discord.Embed(title=f"⚠️ {title}", description=description, color=config.COLOR_WARNING)
        embed.timestamp = datetime.datetime.utcnow()
        return embed

    @staticmethod
    def info(title: str, description: str = "") -> discord.Embed:
        embed = discord.Embed(title=f"ℹ️ {title}", description=description, color=config.COLOR_INFO)
        embed.timestamp = datetime.datetime.utcnow()
        return embed

    @staticmethod
    def ticket_card(
        ticket,
        author: discord.Member,
        assignees: list,
        status_name: str,
        status_color: int,
        status_emoji: str,
        responses: list,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=f"Заявка #{ticket.number:04d}",
            color=status_color,
        )
        embed.set_author(name=str(author), icon_url=author.display_avatar.url)

        status_display = f"{status_emoji} {status_name}" if status_emoji else status_name
        embed.add_field(name="Статус", value=status_display, inline=True)
        embed.add_field(name="Автор", value=author.mention, inline=True)

        if assignees:
            assignees_text = "\n".join(
                m.mention if hasattr(m, "mention") else str(m) for m in assignees
            )
            embed.add_field(name=f"Исполнители ({len(assignees)})", value=assignees_text, inline=True)
        else:
            embed.add_field(name="Исполнители", value="Никто не взялся", inline=True)

        if responses:
            embed.add_field(name="​", value="**Данные заявки:**", inline=False)
            for resp in responses:
                if isinstance(resp, dict):
                    label = resp.get("field_label", "Поле")
                    value = resp.get("value", "")
                else:
                    label = resp.field_label
                    value = resp.value
                value = value if len(value) <= 1024 else value[:1021] + "..."
                embed.add_field(name=label, value=value, inline=False)

        created_ts = int(ticket.created_at.timestamp())
        embed.add_field(name="Создана", value=f"<t:{created_ts}:F>", inline=True)

        if ticket.closed_at:
            closed_ts = int(ticket.closed_at.timestamp())
            embed.add_field(name="Закрыта", value=f"<t:{closed_ts}:F>", inline=True)

        embed.set_footer(text=f"ID: {ticket.id}")
        embed.timestamp = datetime.datetime.utcnow()
        return embed

    @staticmethod
    def panel_embed(
        name: str,
        description: str,
        color: int,
    ) -> discord.Embed:
        embed = discord.Embed(
            title=name,
            description=description or "Нажмите кнопку ниже, чтобы создать заявку.",
            color=color,
        )
        embed.timestamp = datetime.datetime.utcnow()
        return embed

    @staticmethod
    def admin_panel_main() -> discord.Embed:
        embed = discord.Embed(
            title="⚙️ AFC Ticket Bot — Панель управления",
            description=(
                "Добро пожаловать в панель администратора.\n\n"
                "Выберите раздел для управления:"
            ),
            color=config.COLOR_PRIMARY,
        )
        embed.add_field(name="🎫 Панели тикетов", value="Создание и управление панелями заявок", inline=True)
        embed.add_field(name="📋 Формы", value="Конструктор форм для сбора данных", inline=True)
        embed.add_field(name="🏷️ Статусы", value="Настройка статусов заявок", inline=True)
        embed.add_field(name="👥 Роли", value="Управление ролями персонала", inline=True)
        embed.add_field(name="🔔 Уведомления", value="Настройка уведомлений", inline=True)
        embed.add_field(name="📝 Логи", value="Каналы для журналирования", inline=True)
        embed.add_field(name="🔍 Аудит", value="Просмотр журнала действий", inline=True)
        embed.add_field(name="💾 Резервные копии", value="Управление бэкапами", inline=True)
        embed.timestamp = datetime.datetime.utcnow()
        return embed

    @staticmethod
    def audit_log_embed(logs: list) -> discord.Embed:
        embed = discord.Embed(
            title="📋 Журнал аудита",
            color=config.COLOR_INFO,
        )
        if not logs:
            embed.description = "Журнал пуст."
            return embed

        lines = []
        for log in logs:
            ts = int(log.created_at.timestamp())
            lines.append(
                f"<t:{ts}:R> **{log.user_name}** — `{log.action}`"
                + (f" [{log.target_type} #{log.target_id}]" if log.target_id else "")
            )

        embed.description = "\n".join(lines)
        embed.timestamp = datetime.datetime.utcnow()
        return embed
