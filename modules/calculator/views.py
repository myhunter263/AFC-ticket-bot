from __future__ import annotations

import discord
from sqlalchemy import select

from database.models import FoxholeRecipeOverride
from database.session import async_session_maker
from modules.calculator.embeds import calculation_embeds, resource_lines
from services.calculator.aggregate import aggregate_resources
from services.calculator.service import CalculatorService
from services.foxhole_types import CatalogItem


class CalculatorPaginationView(discord.ui.View):
    def __init__(self, author_id: int, embeds: list[discord.Embed]) -> None:
        super().__init__(timeout=300)
        self.author_id = author_id
        self.embeds = embeds
        self.index = 0
        self._sync()

    def _sync(self) -> None:
        self.previous.disabled = self.index == 0
        self.next.disabled = self.index >= len(self.embeds) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message("Это меню другого пользователя.", ephemeral=True)
        return False

    @discord.ui.button(label="Назад", emoji="◀️", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.index = max(0, self.index - 1)
        self._sync()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @discord.ui.button(label="Далее", emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.index = min(len(self.embeds) - 1, self.index + 1)
        self._sync()
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)


class TrainBuilderView(discord.ui.View):
    MAX_UNITS = 15

    def __init__(self, author_id: int, guild_id: int, items: list[CatalogItem]) -> None:
        super().__init__(timeout=900)
        self.author_id = author_id
        self.guild_id = guild_id
        self.items = {item.id: item for item in items if item.id is not None}
        self.quantities: dict[int, int] = {}
        self.selected_id: int | None = None
        self.select = discord.ui.Select(
            placeholder="Добавить локомотив или вагон",
            options=[
                discord.SelectOption(
                    label=item.ru_name[:100], value=str(item.id),
                    description=item.api_name[:100],
                )
                for item in items[:25]
            ],
            row=0,
        )
        self.select.callback = self._selected
        self.add_item(self.select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message("Это состав другого пользователя.", ephemeral=True)
        return False

    def embed(self, total: dict[str, int | float] | None = None) -> discord.Embed:
        count = sum(self.quantities.values())
        lines = [
            f"• {self.items[item_id].ru_name} ×{quantity}"
            for item_id, quantity in self.quantities.items()
        ]
        embed = discord.Embed(
            title=f"Железнодорожный состав · {count}/{self.MAX_UNITS}",
            description="\n".join(lines) or "Выберите локомотив или вагон в меню.",
            color=0x5865F2,
        )
        if total is not None:
            embed.add_field(
                name="Общая стоимость ресурсов",
                value=resource_lines(total)[:1024],
                inline=False,
            )
        return embed

    async def _selected(self, interaction: discord.Interaction) -> None:
        item_id = int(self.select.values[0])
        if sum(self.quantities.values()) >= self.MAX_UNITS:
            await interaction.response.send_message("В составе уже 15 единиц.", ephemeral=True)
            return
        self.selected_id = item_id
        self.quantities[item_id] = self.quantities.get(item_id, 0) + 1
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="+1", style=discord.ButtonStyle.success, row=1)
    async def plus(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.selected_id is None:
            await interaction.response.send_message("Сначала выберите элемент.", ephemeral=True)
            return
        if sum(self.quantities.values()) >= self.MAX_UNITS:
            await interaction.response.send_message("В составе уже 15 единиц.", ephemeral=True)
            return
        self.quantities[self.selected_id] = self.quantities.get(self.selected_id, 0) + 1
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="−1 / удалить", style=discord.ButtonStyle.secondary, row=1)
    async def minus(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.selected_id in self.quantities:
            self.quantities[self.selected_id] -= 1
            if self.quantities[self.selected_id] <= 0:
                del self.quantities[self.selected_id]
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Очистить", style=discord.ButtonStyle.danger, row=1)
    async def clear(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.quantities.clear()
        self.selected_id = None
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Рассчитать", style=discord.ButtonStyle.primary, row=1)
    async def calculate(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not self.quantities:
            await interaction.response.send_message("Состав пуст.", ephemeral=True)
            return
        rows = []
        async with async_session_maker() as session:
            override_rows = list((await session.execute(
                select(FoxholeRecipeOverride).where(
                    FoxholeRecipeOverride.guild_id == self.guild_id,
                    FoxholeRecipeOverride.item_id.in_(self.quantities),
                )
            )).scalars().all())
        by_item: dict[int, list] = {}
        for override in override_rows:
            by_item.setdefault(override.item_id, []).append(override)
        missing = []
        for item_id, quantity in self.quantities.items():
            result = CalculatorService.calculate(
                self.items[item_id], quantity, by_item.get(item_id)
            )
            method = next(
                (row for row in result.methods if row.kind == "override"),
                next(
                    (row for row in result.methods if row.kind == "facility"),
                    next((row for row in result.methods if row.kind != "mpf"), None),
                ),
            )
            if method is None:
                missing.append(self.items[item_id].ru_name)
            else:
                rows.append((method, 1))
        if missing:
            await interaction.response.send_message(
                "Нет рецепта: " + ", ".join(missing), ephemeral=True
            )
            return
        await interaction.response.edit_message(
            embed=self.embed(aggregate_resources(rows)), view=self
        )
