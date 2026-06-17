from __future__ import annotations

import discord


class FormCreateModal(discord.ui.Modal, title="Создать форму"):
    name = discord.ui.TextInput(
        label="Название формы",
        placeholder="Например: Заявка на поддержку",
        max_length=100,
    )
    description = discord.ui.TextInput(
        label="Описание (необязательно)",
        placeholder="Краткое описание формы",
        required=False,
        max_length=500,
        style=discord.TextStyle.long,
    )

    def __init__(self, callback) -> None:
        super().__init__()
        self._callback = callback

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._callback(
            interaction,
            name=self.name.value,
            description=self.description.value or None,
        )


class FormEditModal(discord.ui.Modal, title="Редактировать форму"):
    name = discord.ui.TextInput(label="Название формы", max_length=100)
    description = discord.ui.TextInput(
        label="Описание",
        required=False,
        max_length=500,
        style=discord.TextStyle.long,
    )

    def __init__(self, callback, current_name: str, current_description: str | None) -> None:
        super().__init__()
        self._callback = callback
        self.name.default = current_name
        self.description.default = current_description or ""

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._callback(
            interaction,
            name=self.name.value,
            description=self.description.value or None,
        )


class FormFieldModal(discord.ui.Modal, title="Добавить поле"):
    label = discord.ui.TextInput(
        label="Название поля",
        placeholder="Например: Ваше имя",
        max_length=45,
    )
    placeholder = discord.ui.TextInput(
        label="Подсказка (необязательно)",
        placeholder="Текст-заполнитель внутри поля",
        required=False,
        max_length=100,
    )
    max_length = discord.ui.TextInput(
        label="Макс. символов (1-1024, необязательно)",
        placeholder="1024",
        required=False,
        max_length=4,
    )
    is_required = discord.ui.TextInput(
        label="Обязательное поле? (да/нет)",
        placeholder="да",
        max_length=3,
    )
    field_type = discord.ui.TextInput(
        label="Тип поля (text/long_text)",
        placeholder="text",
        max_length=20,
    )

    def __init__(self, callback) -> None:
        super().__init__()
        self._callback = callback

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw_type = self.field_type.value.strip().lower()
        resolved_type = raw_type if raw_type in ("text", "long_text") else "text"

        try:
            max_len = int(self.max_length.value.strip()) if self.max_length.value.strip() else 1024
            max_len = max(1, min(1024, max_len))
        except ValueError:
            max_len = 1024

        required_raw = self.is_required.value.strip().lower()
        required = required_raw not in ("нет", "no", "false", "0", "н")

        await self._callback(
            interaction,
            label=self.label.value,
            placeholder=self.placeholder.value or None,
            field_type=resolved_type,
            is_required=required,
            max_length=max_len,
        )
