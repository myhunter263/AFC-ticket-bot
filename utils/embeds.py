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
        order_items: list | None = None,
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

        regular_responses = [
            response for response in responses or []
            if not isinstance(response, dict) or response.get("field_type") != "foxhole_order"
        ]
        if regular_responses:
            embed.add_field(name="​", value="**Данные заявки:**", inline=False)
            for resp in regular_responses:
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
    def _format_resources(resources: dict) -> str:
        if not resources:
            return "недоступно"
        return ", ".join(
            f"{amount:,} {config.FOXHOLE_RESOURCE_LABELS.get(resource, resource.upper())}".replace(",", " ")
            for resource, amount in resources.items()
        )

    @staticmethod
    def ticket_order_embeds(order_items: list | None) -> list[discord.Embed]:
        if not order_items:
            return []
        lines: list[str] = []
        for item in order_items:
            if isinstance(item, dict):
                name = item["display_name"]
                quantity = item["quantity"]
                unit = item["unit"]
                snapshot = item.get("cost_snapshot") or {}
            else:
                name = item.display_name
                quantity = item.quantity
                unit = item.unit
                snapshot = item.cost_snapshot or {}
            unit_label = "шт." if unit == "item" else "ящиков"
            standard = EmbedBuilder._format_resources(snapshot.get("factory", {}))
            site = {"Factory": "фабрике", "Garage": "гараже"}.get(
                snapshot.get("factory_site"), snapshot.get("factory_site") or "производстве"
            )
            mpf = EmbedBuilder._format_resources(snapshot.get("mpf", {}))
            mpf_crates = snapshot.get("mpf_crates", 0)
            mpf_text = (
                f"{mpf} на MPF за {mpf_crates} ящиков"
                if mpf_crates else "MPF недоступно"
            )
            lines.append(
                f"• **{name}** — {quantity} {unit_label}\n"
                f"  ({standard} на {site} / {mpf_text})"
            )

        pages: list[str] = []
        current = ""
        for line in lines:
            candidate = f"{current}\n\n{line}" if current else line
            if len(candidate) > 4000 and current:
                pages.append(current)
                current = line
            else:
                current = candidate
        if current:
            pages.append(current)
        return [
            discord.Embed(
                title="Заказ Foxhole" if index == 0 else "Заказ Foxhole · продолжение",
                description=page,
                color=config.COLOR_PRIMARY,
            )
            for index, page in enumerate(pages[:9])
        ]

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
        embed.add_field(name="Каталог Foxhole", value="Предметы, русские названия и алиасы", inline=True)
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
