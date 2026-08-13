from __future__ import annotations

import discord


class ItemSearchModal(discord.ui.Modal, title="Поиск предмета Foxhole"):
    query = discord.ui.TextInput(
        label="Название или алиас",
        placeholder="Например: аргенти, 762, Bardiche",
        max_length=200,
    )

    def __init__(self, callback) -> None:
        super().__init__()
        self._callback = callback

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._callback(interaction, self.query.value.strip())


class ItemValueModal(discord.ui.Modal):
    value = discord.ui.TextInput(label="Значение", max_length=200)

    def __init__(self, title: str, label: str, callback, default: str = "") -> None:
        super().__init__(title=title)
        self._callback = callback
        self.value.label = label
        self.value.default = default

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._callback(interaction, self.value.value.strip())
