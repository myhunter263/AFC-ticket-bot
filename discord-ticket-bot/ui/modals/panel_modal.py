from __future__ import annotations

import discord


class PanelCreateModal(discord.ui.Modal, title="Создать панель тикетов"):
    name = discord.ui.TextInput(
        label="Название панели",
        placeholder="Например: Техническая поддержка",
        max_length=100,
    )
    description = discord.ui.TextInput(
        label="Описание",
        placeholder="Нажмите кнопку ниже, чтобы создать заявку.",
        required=False,
        max_length=500,
        style=discord.TextStyle.long,
    )
    button_label = discord.ui.TextInput(
        label="Текст кнопки",
        placeholder="Создать заявку",
        max_length=80,
        default="Создать заявку",
    )
    button_emoji = discord.ui.TextInput(
        label="Эмодзи кнопки (необязательно)",
        placeholder="🎫",
        required=False,
        max_length=10,
    )
    color_hex = discord.ui.TextInput(
        label="Цвет embed (HEX, например #5865F2)",
        placeholder="#5865F2",
        max_length=7,
        default="#5865F2",
    )

    def __init__(self, callback) -> None:
        super().__init__()
        self._callback = callback

    async def on_submit(self, interaction: discord.Interaction) -> None:
        color = _parse_hex_color(self.color_hex.value, 0x5865F2)
        await self._callback(
            interaction,
            name=self.name.value,
            description=self.description.value or None,
            button_label=self.button_label.value or "Создать заявку",
            button_emoji=self.button_emoji.value.strip() or None,
            color=color,
        )


class PanelEditModal(discord.ui.Modal, title="Редактировать панель"):
    name = discord.ui.TextInput(label="Название панели", max_length=100)
    description = discord.ui.TextInput(
        label="Описание",
        required=False,
        max_length=500,
        style=discord.TextStyle.long,
    )
    button_label = discord.ui.TextInput(label="Текст кнопки", max_length=80)
    button_emoji = discord.ui.TextInput(
        label="Эмодзи кнопки (необязательно)",
        required=False,
        max_length=10,
    )
    color_hex = discord.ui.TextInput(label="Цвет embed (HEX)", max_length=7)

    def __init__(
        self,
        callback,
        current_name: str,
        current_description: str | None,
        current_button_label: str,
        current_button_emoji: str | None,
        current_color: int,
    ) -> None:
        super().__init__()
        self._callback = callback
        self.name.default = current_name
        self.description.default = current_description or ""
        self.button_label.default = current_button_label
        self.button_emoji.default = current_button_emoji or ""
        self.color_hex.default = f"#{current_color:06X}"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        color = _parse_hex_color(self.color_hex.value, 0x5865F2)
        await self._callback(
            interaction,
            name=self.name.value,
            description=self.description.value or None,
            button_label=self.button_label.value or "Создать заявку",
            button_emoji=self.button_emoji.value.strip() or None,
            color=color,
        )


def _parse_hex_color(value: str, default: int) -> int:
    cleaned = value.strip().lstrip("#")
    try:
        return int(cleaned, 16)
    except ValueError:
        return default
