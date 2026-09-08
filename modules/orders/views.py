import uuid

import discord

from integrations.backend.client import BackendError

CATEGORIES = {"vehicle": "Техника", "ammunition": "Боеприпасы", "equipment": "Оружие / экипировка",
              "material": "Материалы", "delivery": "Доставка", "other": "Другое"}
UNITS = {"item": "шт.", "crate": "ящ.", "batch": "партий", "request": "запросов"}


async def error(interaction, text):
    if interaction.response.is_done():
        await interaction.followup.send(str(text)[:1900], ephemeral=True)
    else:
        await interaction.response.send_message(str(text)[:1900], ephemeral=True)


class SafeView(discord.ui.View):
    async def on_error(self, interaction, exc, item):
        await error(interaction, str(exc) if isinstance(exc, BackendError) else "Не удалось выполнить действие. Повторите попытку")


class SafeModal(discord.ui.Modal):
    async def on_error(self, interaction, exc):
        await error(interaction, str(exc) if isinstance(exc, (BackendError, ValueError)) else "Не удалось сохранить форму")


class OrderPanelView(SafeView):
    def __init__(self, client, guild_id):
        super().__init__(timeout=None)
        self.client, self.guild_id = client, guild_id

    @discord.ui.button(label="Сделать заказ", emoji="📦", custom_id="crm:order:create", style=discord.ButtonStyle.primary)
    async def create(self, interaction, button):
        if interaction.guild_id != self.guild_id:
            return await error(interaction, "Панель недоступна на этом сервере")
        cart = CartView(self.client, interaction.user.id)
        await interaction.response.send_message(embed=cart.embed(), view=cart, ephemeral=True)


class CartView(SafeView):
    def __init__(self, client, author_id):
        super().__init__(timeout=900)
        self.client, self.author_id = client, author_id
        self.items = []
        self.delivery = ""
        self.comment = ""
        self.key = str(uuid.uuid4())
        self.creating = False
        self.confirmed = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await error(interaction, "Это корзина другого пользователя")
            return False
        return True

    def embed(self):
        lines = [f"{n}. {i['name']} ×{i['quantity']} {UNITS[i['unit']]}" for n, i in enumerate(self.items, 1)]
        text = "\n".join(lines) or "Добавьте позиции заказа. Корзина действует 15 минут."
        embed = discord.Embed(title="Ваш заказ", description=text[:3500], color=0x5865F2)
        if self.delivery:
            embed.add_field(name="Доставка", value=self.delivery, inline=False)
            embed.add_field(name="Комментарий", value=self.comment[:1000] or "—", inline=False)
        return embed

    async def render(self, interaction):
        self.confirm.disabled = not self.items or not self.delivery or self.creating
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Добавить позицию", style=discord.ButtonStyle.primary, row=0)
    async def add(self, interaction, button):
        if len(self.items) >= 30:
            return await error(interaction, "В заказе допускается до 30 позиций")
        await interaction.response.edit_message(embed=self.embed(), view=CategoryView(self))

    @discord.ui.button(label="Изменить / удалить", row=0)
    async def edit(self, interaction, button):
        if not self.items:
            return await error(interaction, "Корзина пуста")
        await interaction.response.send_modal(EditCartModal(self))

    @discord.ui.button(label="Доставка и комментарий", row=1)
    async def destination(self, interaction, button):
        await interaction.response.send_modal(DeliveryModal(self))

    @discord.ui.button(label="Подтвердить", style=discord.ButtonStyle.success, row=1, disabled=True)
    async def confirm(self, interaction, button):
        if self.creating or self.confirmed:
            return await error(interaction, "Заказ уже отправлен")
        if not self.items or not self.delivery:
            return await error(interaction, "Добавьте позиции и точку доставки")
        self.creating = True
        await interaction.response.defer(ephemeral=True)
        try:
            row = await self.client.request("POST", "/api/v1/orders", member=interaction.user, data={
                "idempotency_key": self.key, "items": self.items, "delivery_location": self.delivery, "comment": self.comment,
            })
            self.confirmed = True
            self.stop()
            await interaction.edit_original_response(content=f"Заказ #{row['public_number']:06d} создан.", embed=None, view=None)
        finally:
            self.creating = False

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.danger, row=2)
    async def cancel(self, interaction, button):
        self.stop()
        await interaction.response.edit_message(content="Оформление отменено.", embed=None, view=None)


class OwnedView(SafeView):
    def __init__(self, cart):
        super().__init__(timeout=900)
        self.cart = cart

    async def interaction_check(self, interaction):
        return await self.cart.interaction_check(interaction)

    @discord.ui.button(label="Назад в корзину", row=4)
    async def back(self, interaction, button):
        await self.cart.render(interaction)


class CategoryView(OwnedView):
    def __init__(self, cart):
        super().__init__(cart)
        select = discord.ui.Select(placeholder="Что нужно заказать?", options=[discord.SelectOption(label=v, value=k) for k, v in CATEGORIES.items()])
        select.callback = self.choose
        self.select = select
        self.add_item(select)

    async def choose(self, interaction):
        category = self.select.values[0]
        if category in {"delivery", "other"}:
            await interaction.response.send_modal(FreeRequestModal(self.cart, category))
        else:
            await interaction.response.send_modal(SearchModal(self.cart, category))


class SearchModal(SafeModal, title="Поиск предмета"):
    query = discord.ui.TextInput(label="Название или алиас", max_length=100)

    def __init__(self, cart, category):
        super().__init__()
        self.cart, self.category = cart, category

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        rows = await self.cart.client.request("GET", "/api/v1/catalog", member=interaction.user, params={"search": str(self.query), "limit": 25})
        if not rows:
            return await error(interaction, "Предмет не найден. Попробуйте другое название")
        await interaction.edit_original_response(view=ItemSelectView(self.cart, self.category, rows))


class ItemSelectView(OwnedView):
    def __init__(self, cart, category, rows):
        super().__init__(cart)
        self.category, self.rows = category, rows
        self.selected = rows[0]
        self.unit = self.selected["unit"]
        self.selector = discord.ui.Select(placeholder="Выберите предмет", options=[discord.SelectOption(label=r["name"][:100], value=str(r["id"])) for r in rows])
        self.selector.callback = self.choose
        self.add_item(self.selector)
        self.units = discord.ui.Select(placeholder="Единица: выберите явно", options=[discord.SelectOption(label="Штуки", value="item"), discord.SelectOption(label="Ящики", value="crate")], row=1)
        self.units.callback = self.choose_unit
        self.add_item(self.units)

    async def choose(self, interaction):
        self.selected = next(r for r in self.rows if str(r["id"]) == self.selector.values[0])
        self.unit = self.selected["unit"]
        await interaction.response.edit_message(content=f"{self.selected['name']} · единица по умолчанию: {UNITS[self.unit]}", view=self)

    async def choose_unit(self, interaction):
        self.unit = self.units.values[0]
        await interaction.response.edit_message(content=f"{self.selected['name']} · {UNITS[self.unit]}", view=self)

    @discord.ui.button(label="Указать количество", style=discord.ButtonStyle.primary, row=2)
    async def amount(self, interaction, button):
        await interaction.response.send_modal(QuantityModal(self.cart, self.category, self.selected, self.unit))


class QuantityModal(SafeModal, title="Количество"):
    quantity = discord.ui.TextInput(label="Количество (1–100000)", max_length=6)

    def __init__(self, cart, category, item, unit):
        super().__init__()
        self.cart, self.category, self.item, self.unit = cart, category, item, unit
        self.quantity.label = f"Количество, {UNITS[unit]} (1–100000)"

    async def on_submit(self, interaction):
        quantity = int(str(self.quantity))
        if not 1 <= quantity <= 100000:
            raise ValueError("Количество должно быть от 1 до 100000")
        self.cart.items.append({"item_id": self.item["id"], "name": self.item["name"], "category": self.category,
                                "quantity": quantity, "unit": self.unit})
        self.cart.key = str(uuid.uuid4())
        await self.cart.render(interaction)


class FreeRequestModal(SafeModal, title="Логистический запрос"):
    description = discord.ui.TextInput(label="Что требуется?", max_length=200)

    def __init__(self, cart, category):
        super().__init__()
        self.cart, self.category = cart, category

    async def on_submit(self, interaction):
        self.cart.items.append({"name": str(self.description), "category": self.category, "quantity": 1, "unit": "request"})
        self.cart.key = str(uuid.uuid4())
        await self.cart.render(interaction)


class DeliveryModal(SafeModal, title="Доставка"):
    location = discord.ui.TextInput(label="Точка доставки", max_length=300)
    comment = discord.ui.TextInput(label="Комментарий", style=discord.TextStyle.paragraph, max_length=2000, required=False)

    def __init__(self, cart):
        super().__init__()
        self.cart = cart
        self.location.default, self.comment.default = cart.delivery, cart.comment

    async def on_submit(self, interaction):
        self.cart.delivery, self.cart.comment = str(self.location), str(self.comment)
        self.cart.key = str(uuid.uuid4())
        await self.cart.render(interaction)


class EditCartModal(SafeModal, title="Изменить позицию"):
    position = discord.ui.TextInput(label="Номер позиции", max_length=2)
    quantity = discord.ui.TextInput(label="Новое количество; 0 — удалить", max_length=6)

    def __init__(self, cart):
        super().__init__()
        self.cart = cart

    async def on_submit(self, interaction):
        index, quantity = int(str(self.position)) - 1, int(str(self.quantity))
        if not 0 <= index < len(self.cart.items) or not 0 <= quantity <= 100000:
            raise ValueError("Проверьте номер позиции и количество")
        if quantity == 0:
            self.cart.items.pop(index)
        else:
            self.cart.items[index]["quantity"] = quantity
        self.cart.key = str(uuid.uuid4())
        await self.cart.render(interaction)


def order_embed(row):
    lines = [f"{i['name']} ×{i['quantity']} {UNITS[i['unit']]}" for i in row["items"]]
    embed = discord.Embed(title=f"Заказ #{row['public_number']:06d} · {row['status_label']}", description="\n".join(lines)[:3500], color=0x5865F2)
    embed.add_field(name="Заказчик", value=f"<@{row['discord_user_id']}>")
    embed.add_field(name="Ответственный", value=f"<@{row['assigned_user_id']}>" if row["assigned_user_id"] else "Не назначен")
    embed.add_field(name="Доставка", value=row["delivery_location"], inline=False)
    if row["comment"]:
        embed.add_field(name="Комментарий", value=row["comment"][:1000], inline=False)
    embed.set_footer(text=f"Заказ ID {row['id']} · версия {row['version']}")
    return embed


class OrderActionView(SafeView):
    def __init__(self, client, order_id):
        super().__init__(timeout=None)
        self.client, self.order_id = client, order_id
        for label, action, style in (("Принять", "accept", discord.ButtonStyle.success),
                                     ("Открыть", "open", discord.ButtonStyle.primary),
                                     ("Отклонить", "reject", discord.ButtonStyle.danger)):
            button = discord.ui.Button(label=label, custom_id=f"crm:{action}:{order_id}", style=style)
            async def callback(interaction, action=action):
                await interaction.response.defer(ephemeral=True)
                row = await client.request("GET", f"/api/v1/orders/{order_id}", member=interaction.user)
                if action != "open":
                    path = "accept" if action == "accept" else "status"
                    data = {"version": row["version"]}
                    if action == "reject":
                        data["status"] = "REJECTED"
                    row = await client.request("POST", f"/api/v1/orders/{order_id}/{path}", member=interaction.user, data=data)
                await interaction.followup.send(embed=order_embed(row), ephemeral=True)
            button.callback = callback
            self.add_item(button)
