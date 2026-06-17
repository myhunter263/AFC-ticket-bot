from __future__ import annotations

import discord

from database.session import async_session_maker
from services.audit_service import AuditService
from services.form_service import FormService
from ui.modals.form_modal import FormCreateModal, FormEditModal, FormFieldModal
from utils.embeds import EmbedBuilder
from utils.permissions import PermissionChecker


class FormListView(discord.ui.View):
    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=300)
        self.guild_id = guild_id

    @discord.ui.button(label="Создать форму", style=discord.ButtonStyle.success, emoji="➕", row=0)
    async def create_form(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            if not await PermissionChecker.is_bot_admin(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
                )
                return

        async def on_submit(inter: discord.Interaction, name: str, description) -> None:
            async with async_session_maker() as session:
                form = await FormService.create(
                    session,
                    guild_id=self.guild_id,
                    name=name,
                    description=description,
                    created_by=inter.user.id,
                )
                await AuditService.log(
                    session,
                    guild_id=self.guild_id,
                    user_id=inter.user.id,
                    user_name=str(inter.user),
                    action="create_form",
                    target_type="form",
                    target_id=form.id,
                    details={"name": name},
                )
                await session.commit()
                form_id = form.id
                form_name = form.name

            embed = EmbedBuilder.success(
                "Форма создана",
                f"Форма **{form_name}** (ID: {form_id}) создана.\n"
                "Теперь добавьте поля через «Управление полями».",
            )
            await inter.response.send_message(embed=embed, ephemeral=True)

        modal = FormCreateModal(on_submit)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Мои формы", style=discord.ButtonStyle.primary, emoji="📋", row=0)
    async def list_forms(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            forms = await FormService.get_all(session, self.guild_id)

        if not forms:
            await interaction.response.send_message(
                embed=EmbedBuilder.info("Формы", "Формы не созданы. Нажмите «Создать форму»."),
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="📋 Формы", color=0x5865F2)
        for f in forms:
            active_fields = [x for x in f.fields if x.is_active]
            status = "✅ Активна" if f.is_active else "🔴 Отключена"
            embed.add_field(
                name=f"[{f.id}] {f.name}",
                value=f"{status} | Полей: {len(active_fields)}",
                inline=False,
            )

        view = FormSelectView(self.guild_id, forms)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class FormSelectView(discord.ui.View):
    def __init__(self, guild_id: int, forms: list) -> None:
        super().__init__(timeout=180)
        self.guild_id = guild_id

        options = [
            discord.SelectOption(
                label=f.name[:100],
                value=str(f.id),
                description=f"ID: {f.id} | Полей: {len([x for x in f.fields if x.is_active])}",
            )
            for f in forms[:25]
        ]

        select = discord.ui.Select(
            placeholder="Выберите форму для управления...",
            options=options,
        )
        select.callback = self._select_callback
        self.add_item(select)

    async def _select_callback(self, interaction: discord.Interaction) -> None:
        form_id = int(interaction.data["values"][0])

        async with async_session_maker() as session:
            if not await PermissionChecker.is_bot_admin(interaction, session):
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Нет доступа"), ephemeral=True
                )
                return
            form = await FormService.get_by_id(session, form_id)
            if not form:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Форма не найдена."), ephemeral=True
                )
                return
            form_name = form.name
            fields = [
                {
                    "id": f.id,
                    "label": f.label,
                    "field_type": f.field_type,
                    "is_required": f.is_required,
                    "is_active": f.is_active,
                    "order": f.order,
                }
                for f in form.fields
            ]

        embed = discord.Embed(
            title=f"📝 Форма: {form_name}",
            color=0x5865F2,
        )
        if fields:
            for fd in sorted(fields, key=lambda x: x["order"]):
                status_icon = "✅" if fd["is_active"] else "🔴"
                req_icon = "❗" if fd["is_required"] else "○"
                embed.add_field(
                    name=f"{status_icon} {req_icon} [{fd['id']}] {fd['label']}",
                    value=f"Тип: `{fd['field_type']}`",
                    inline=False,
                )
        else:
            embed.description = "В форме нет полей. Добавьте поля ниже."

        view = FormDetailView(self.guild_id, form_id, form_name)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class FormDetailView(discord.ui.View):
    def __init__(self, guild_id: int, form_id: int, form_name: str) -> None:
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.form_id = form_id
        self.form_name = form_name

    @discord.ui.button(label="Добавить поле", style=discord.ButtonStyle.success, emoji="➕", row=0)
    async def add_field(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async def on_submit(inter: discord.Interaction, **kwargs) -> None:
            async with async_session_maker() as session:
                form = await FormService.get_by_id(session, self.form_id)
                if not form:
                    await inter.response.send_message(
                        embed=EmbedBuilder.error("Ошибка", "Форма не найдена."), ephemeral=True
                    )
                    return
                try:
                    field = await FormService.add_field(session, form, **kwargs)
                    await AuditService.log(
                        session,
                        guild_id=self.guild_id,
                        user_id=inter.user.id,
                        user_name=str(inter.user),
                        action="add_form_field",
                        target_type="form",
                        target_id=self.form_id,
                        details={"label": field.label},
                    )
                    await session.commit()
                    field_label = field.label
                except ValueError as e:
                    await inter.response.send_message(
                        embed=EmbedBuilder.error("Ошибка", str(e)), ephemeral=True
                    )
                    return

            await inter.response.send_message(
                embed=EmbedBuilder.success("Поле добавлено", f"Поле **{field_label}** добавлено в форму."),
                ephemeral=True,
            )

        modal = FormFieldModal(on_submit)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Редактировать форму", style=discord.ButtonStyle.primary, emoji="✏️", row=0)
    async def edit_form(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            form = await FormService.get_by_id(session, self.form_id, with_fields=False)
            if not form:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Форма не найдена."), ephemeral=True
                )
                return
            current_name = form.name
            current_desc = form.description

        async def on_submit(inter: discord.Interaction, name: str, description) -> None:
            async with async_session_maker() as session:
                f = await FormService.get_by_id(session, self.form_id, with_fields=False)
                if f:
                    await FormService.update(session, f, name=name, description=description)
                    await AuditService.log(
                        session,
                        guild_id=self.guild_id,
                        user_id=inter.user.id,
                        user_name=str(inter.user),
                        action="update_form",
                        target_type="form",
                        target_id=self.form_id,
                    )
                    await session.commit()
                    self.form_name = name

            await inter.response.send_message(
                embed=EmbedBuilder.success("Форма обновлена", f"Форма переименована в **{name}**."),
                ephemeral=True,
            )

        modal = FormEditModal(on_submit, current_name, current_desc)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Дублировать", style=discord.ButtonStyle.secondary, emoji="📑", row=0)
    async def duplicate_form(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        async with async_session_maker() as session:
            form = await FormService.get_by_id(session, self.form_id)
            if not form:
                await interaction.followup.send(
                    embed=EmbedBuilder.error("Ошибка", "Форма не найдена."), ephemeral=True
                )
                return
            new_form = await FormService.duplicate(session, form, created_by=interaction.user.id)
            await AuditService.log(
                session,
                guild_id=self.guild_id,
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action="duplicate_form",
                target_type="form",
                target_id=self.form_id,
                details={"new_form_id": new_form.id},
            )
            await session.commit()
            new_name = new_form.name

        await interaction.followup.send(
            embed=EmbedBuilder.success("Форма скопирована", f"Создана копия: **{new_name}**"),
            ephemeral=True,
        )

    @discord.ui.button(label="Удалить форму", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
    async def delete_form(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view = ConfirmDeleteView(self.guild_id, self.form_id, self.form_name)
        embed = EmbedBuilder.warning(
            "Подтверждение удаления",
            f"Вы уверены, что хотите удалить форму **{self.form_name}**?\n"
            "Все поля и связанные данные будут удалены.",
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Отключить/Включить поле", style=discord.ButtonStyle.secondary, emoji="🔄", row=1)
    async def toggle_field(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            form = await FormService.get_by_id(session, self.form_id)
            if not form or not form.fields:
                await interaction.response.send_message(
                    embed=EmbedBuilder.info("Нет полей", "В форме нет полей."), ephemeral=True
                )
                return
            fields = form.fields

        options = [
            discord.SelectOption(
                label=f.label[:100],
                value=str(f.id),
                description=f"Тип: {f.field_type} | {'✅ Активно' if f.is_active else '🔴 Отключено'}",
                emoji="✅" if f.is_active else "🔴",
            )
            for f in fields[:25]
        ]

        view = FieldToggleView(self.guild_id, self.form_id, options)
        await interaction.response.send_message(
            embed=EmbedBuilder.info("Выберите поле", "Выберите поле для включения/отключения:"),
            view=view,
            ephemeral=True,
        )


class FieldToggleView(discord.ui.View):
    def __init__(self, guild_id: int, form_id: int, options: list) -> None:
        super().__init__(timeout=120)
        self.guild_id = guild_id
        self.form_id = form_id

        select = discord.ui.Select(placeholder="Выберите поле...", options=options)
        select.callback = self._toggle
        self.add_item(select)

    async def _toggle(self, interaction: discord.Interaction) -> None:
        field_id = int(interaction.data["values"][0])
        async with async_session_maker() as session:
            field = await FormService.get_field_by_id(session, field_id)
            if not field:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error("Ошибка", "Поле не найдено."), ephemeral=True
                )
                return
            new_state = not field.is_active
            await FormService.update_field(session, field, is_active=new_state)
            await AuditService.log(
                session,
                guild_id=self.guild_id,
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                action="toggle_form_field",
                target_type="form",
                target_id=self.form_id,
                details={"field_id": field_id, "is_active": new_state},
            )
            await session.commit()
            label = field.label

        state_str = "включено" if new_state else "отключено"
        await interaction.response.send_message(
            embed=EmbedBuilder.success("Обновлено", f"Поле **{label}** {state_str}."),
            ephemeral=True,
        )


class ConfirmDeleteView(discord.ui.View):
    def __init__(self, guild_id: int, form_id: int, form_name: str) -> None:
        super().__init__(timeout=60)
        self.guild_id = guild_id
        self.form_id = form_id
        self.form_name = form_name

    @discord.ui.button(label="Да, удалить", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with async_session_maker() as session:
            form = await FormService.get_by_id(session, self.form_id)
            if form:
                await FormService.delete(session, form)
                await AuditService.log(
                    session,
                    guild_id=self.guild_id,
                    user_id=interaction.user.id,
                    user_name=str(interaction.user),
                    action="delete_form",
                    target_type="form",
                    target_id=self.form_id,
                    details={"name": self.form_name},
                )
                await session.commit()

        for item in self.children:
            item.disabled = True  # type: ignore

        await interaction.response.edit_message(
            embed=EmbedBuilder.success("Форма удалена", f"Форма **{self.form_name}** удалена."),
            view=self,
        )

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            embed=EmbedBuilder.info("Отменено", "Удаление отменено."),
            view=None,
        )
