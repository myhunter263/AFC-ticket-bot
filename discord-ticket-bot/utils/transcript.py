from __future__ import annotations

import datetime
import io
from typing import List

import discord


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Транскрипт тикета #{ticket_number}</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #36393f; color: #dcddde; margin: 0; padding: 0; }}
  .header {{ background: #2f3136; padding: 20px 30px; border-bottom: 2px solid #5865F2; }}
  .header h1 {{ margin: 0; color: #fff; font-size: 1.5em; }}
  .header .meta {{ color: #8e9297; font-size: 0.9em; margin-top: 8px; }}
  .responses {{ background: #2f3136; margin: 20px 30px; border-radius: 8px; padding: 20px; }}
  .responses h2 {{ color: #5865F2; margin-top: 0; }}
  .field {{ margin-bottom: 16px; }}
  .field-label {{ color: #8e9297; font-size: 0.85em; text-transform: uppercase; font-weight: 700; margin-bottom: 4px; }}
  .field-value {{ background: #202225; padding: 10px 14px; border-radius: 4px; border-left: 3px solid #5865F2; white-space: pre-wrap; }}
  .messages {{ margin: 0 30px 30px; }}
  .messages h2 {{ color: #5865F2; }}
  .message {{ display: flex; gap: 12px; margin-bottom: 16px; padding: 8px 0; border-bottom: 1px solid #40444b; }}
  .avatar {{ width: 40px; height: 40px; border-radius: 50%; background: #5865F2; flex-shrink: 0; display: flex; align-items: center; justify-content: center; font-weight: bold; color: #fff; font-size: 1.1em; }}
  .avatar img {{ width: 40px; height: 40px; border-radius: 50%; }}
  .msg-body {{ flex: 1; }}
  .msg-header {{ display: flex; align-items: baseline; gap: 8px; }}
  .msg-author {{ font-weight: 700; color: #fff; }}
  .msg-time {{ font-size: 0.75em; color: #72767d; }}
  .msg-content {{ margin-top: 4px; line-height: 1.5; white-space: pre-wrap; }}
  .bot-tag {{ background: #5865F2; color: #fff; font-size: 0.7em; padding: 1px 5px; border-radius: 3px; vertical-align: middle; }}
  .footer {{ background: #2f3136; padding: 16px 30px; color: #72767d; font-size: 0.85em; text-align: center; }}
  .status-badge {{ display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 0.8em; font-weight: 700; margin-left: 10px; }}
</style>
</head>
<body>
<div class="header">
  <h1>🎫 Транскрипт заявки #{ticket_number:04d}</h1>
  <div class="meta">
    Сервер: {guild_name} &nbsp;|&nbsp;
    Автор: {author_name} &nbsp;|&nbsp;
    Статус: {status_name} &nbsp;|&nbsp;
    Создана: {created_at} &nbsp;|&nbsp;
    Закрыта: {closed_at} &nbsp;|&nbsp;
    Сообщений: {message_count}
  </div>
</div>

{responses_section}

<div class="messages">
  <h2>💬 История сообщений</h2>
  {messages_html}
</div>

<div class="footer">
  Экспортировано {exported_at} | Discord Ticket Bot
</div>
</body>
</html>"""


class TranscriptGenerator:

    @staticmethod
    async def generate_html(
        ticket,
        channel: discord.TextChannel,
        guild: discord.Guild,
        responses: list,
        status_name: str,
    ) -> io.BytesIO:
        messages: List[discord.Message] = []
        async for msg in channel.history(limit=500, oldest_first=True):
            messages.append(msg)

        responses_html = ""
        if responses:
            fields_html = ""
            for resp in responses:
                val = resp.value.replace("<", "&lt;").replace(">", "&gt;")
                fields_html += f'<div class="field"><div class="field-label">{resp.field_label}</div><div class="field-value">{val}</div></div>'
            responses_html = f'<div class="responses"><h2>📋 Данные заявки</h2>{fields_html}</div>'

        messages_html_parts = []
        for msg in messages:
            if msg.author.bot and not msg.embeds and not msg.content:
                continue
            avatar_html = (
                f'<img src="{msg.author.display_avatar.url}" alt="avatar">'
                if msg.author.display_avatar
                else msg.author.display_name[0].upper()
            )
            bot_tag = '<span class="bot-tag">BOT</span>' if msg.author.bot else ""
            ts = msg.created_at.strftime("%d.%m.%Y %H:%M")
            content = msg.content.replace("<", "&lt;").replace(">", "&gt;") if msg.content else ""
            if msg.embeds:
                for emb in msg.embeds:
                    if emb.title:
                        content += f"\n[Embed: {emb.title}]"
            messages_html_parts.append(
                f'<div class="message">'
                f'<div class="avatar">{avatar_html}</div>'
                f'<div class="msg-body">'
                f'<div class="msg-header"><span class="msg-author">{msg.author.display_name}</span>{bot_tag}'
                f'<span class="msg-time">{ts}</span></div>'
                f'<div class="msg-content">{content}</div>'
                f"</div></div>"
            )

        author = guild.get_member(ticket.author_id)
        author_name = str(author) if author else f"ID:{ticket.author_id}"
        created_at = ticket.created_at.strftime("%d.%m.%Y %H:%M")
        closed_at = ticket.closed_at.strftime("%d.%m.%Y %H:%M") if ticket.closed_at else "Не закрыта"
        exported_at = datetime.datetime.utcnow().strftime("%d.%m.%Y %H:%M UTC")

        html = HTML_TEMPLATE.format(
            ticket_number=ticket.number,
            guild_name=guild.name.replace("<", "&lt;").replace(">", "&gt;"),
            author_name=author_name,
            status_name=status_name,
            created_at=created_at,
            closed_at=closed_at,
            message_count=len(messages),
            responses_section=responses_html,
            messages_html="\n".join(messages_html_parts) if messages_html_parts else "<p>Нет сообщений.</p>",
            exported_at=exported_at,
        )

        return io.BytesIO(html.encode("utf-8"))

    @staticmethod
    async def generate_txt(
        ticket,
        channel: discord.TextChannel,
        guild: discord.Guild,
        responses: list,
        status_name: str,
    ) -> io.BytesIO:
        lines = [
            f"=== ТРАНСКРИПТ ЗАЯВКИ #{ticket.number:04d} ===",
            f"Сервер: {guild.name}",
            f"Статус: {status_name}",
            f"Автор ID: {ticket.author_id}",
            f"Создана: {ticket.created_at.strftime('%d.%m.%Y %H:%M')}",
            f"Закрыта: {ticket.closed_at.strftime('%d.%m.%Y %H:%M') if ticket.closed_at else 'нет'}",
            "",
        ]

        if responses:
            lines.append("--- ДАННЫЕ ЗАЯВКИ ---")
            for resp in responses:
                lines.append(f"{resp.field_label}: {resp.value}")
            lines.append("")

        lines.append("--- СООБЩЕНИЯ ---")
        async for msg in channel.history(limit=500, oldest_first=True):
            if not msg.content and not msg.embeds:
                continue
            ts = msg.created_at.strftime("%d.%m.%Y %H:%M")
            lines.append(f"[{ts}] {msg.author.display_name}: {msg.content}")

        lines.append("")
        lines.append(f"Экспортировано: {datetime.datetime.utcnow().strftime('%d.%m.%Y %H:%M UTC')}")

        return io.BytesIO("\n".join(lines).encode("utf-8"))
