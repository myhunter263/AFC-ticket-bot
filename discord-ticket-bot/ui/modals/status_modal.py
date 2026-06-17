from __future__ import annotations

import discord


class StatusCreateModal(discord.ui.Modal, title="Создать статус"):
    name = discord.ui.TextInput(
        label="Название статуса",
        placeholder="Например: В работе",
        max_length=50,
    )
    emoji = discord.ui.TextInput(
        label="Эмодзи (необязательно)",
        placeholder="⚙️",
        required=False,
        max_length=10,
    )
    color_hex = discord.ui.TextInput(
        label="Цвет (HEX, например #FEE75C)",
        placeholder="#5865F2",
        max_length=7,
    )
    is_closed = discord.ui.TextInput(
        label="Означает закрытие тикета? (да/нет)",
        placeholder="нет",
        max_length=3,
    )
    is_default = discord.ui.TextInput(
        label="Статус по умолчанию? (да/нет)",
        placeholder="нет",
        max_length=3,
    )

    def __init__(self, callback) -> None:
        super().__init__()
        self._callback = callback

    async def on_submit(self, interaction: discord.Interaction) -> None:
        color = _parse_hex_color(self.color_hex.value, 0x5865F2)
        closed_raw = self.is_closed.value.strip().lower()
        is_closed = closed_raw in ("да", "yes", "true", "1", "y")
        default_raw = self.is_default.value.strip().lower()
        is_default = default_raw in ("да", "yes", "true", "1", "y")

        await self._callback(
            interaction,
            name=self.name.value,
            emoji=self.emoji.value.strip() or None,
            color=color,
            is_closed=is_closed,
            is_default=is_default,
        )


class StatusEditModal(discord.ui.Modal, title="Редактировать статус"):
    name = discord.ui.TextInput(label="Название статуса", max_length=50)
    emoji = discord.ui.TextInput(
        label="Эмодзи (необязательно)",
        required=False,
        max_length=10,
    )
    color_hex = discord.ui.TextInput(
        label="Цвет (HEX)",
        max_length=7,
    )
    is_closed = discord.ui.TextInput(
        label="Означает закрытие тикета? (да/нет)",
        max_length=3,
    )
    is_default = discord.ui.TextInput(
        label="Статус по умолчанию? (да/нет)",
        max_length=3,
    )

    def __init__(
        self,
        callback,
        current_name: str,
        current_emoji: str | None,
        current_color: int,
        current_is_closed: bool,
        current_is_default: bool,
    ) -> None:
        super().__init__()
        self._callback = callback
        self.name.default = current_name
        self.emoji.default = current_emoji or ""
        self.color_hex.default = f"#{current_color:06X}"
        self.is_closed.default = "да" if current_is_closed else "нет"
        self.is_default.default = "да" if current_is_default else "нет"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        color = _parse_hex_color(self.color_hex.value, 0x5865F2)
        closed_raw = self.is_closed.value.strip().lower()
        is_closed = closed_raw in ("да", "yes", "true", "1", "y")
        default_raw = self.is_default.value.strip().lower()
        is_default = default_raw in ("да", "yes", "true", "1", "y")

        await self._callback(
            interaction,
            name=self.name.value,
            emoji=self.emoji.value.strip() or None,
            color=color,
            is_closed=is_closed,
            is_default=is_default,
        )


def _parse_hex_color(value: str, default: int) -> int:
    cleaned = value.strip().lstrip("#")
    try:
        return int(cleaned, 16)
    except ValueError:
        return default
