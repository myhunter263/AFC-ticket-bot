from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import config
from database.models import FormField, TicketForm


class FormService:

    @staticmethod
    async def get_all(session: AsyncSession, guild_id: int) -> list[TicketForm]:
        result = await session.execute(
            select(TicketForm)
            .where(TicketForm.guild_id == guild_id)
            .options(selectinload(TicketForm.fields))
            .order_by(TicketForm.id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(
        session: AsyncSession, form_id: int, with_fields: bool = True
    ) -> Optional[TicketForm]:
        query = select(TicketForm).where(TicketForm.id == form_id)
        if with_fields:
            query = query.options(selectinload(TicketForm.fields))
        result = await session.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        session: AsyncSession,
        guild_id: int,
        name: str,
        description: Optional[str],
        created_by: int,
    ) -> TicketForm:
        form = TicketForm(
            guild_id=guild_id,
            name=name,
            description=description,
            created_by=created_by,
        )
        session.add(form)
        await session.flush()
        return form

    @staticmethod
    async def update(
        session: AsyncSession,
        form: TicketForm,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> TicketForm:
        if name is not None:
            form.name = name
        if description is not None:
            form.description = description if description.strip() else None
        if is_active is not None:
            form.is_active = is_active
        await session.flush()
        return form

    @staticmethod
    async def delete(session: AsyncSession, form: TicketForm) -> None:
        await session.delete(form)
        await session.flush()

    @staticmethod
    async def duplicate(
        session: AsyncSession,
        form: TicketForm,
        created_by: int,
    ) -> TicketForm:
        new_form = TicketForm(
            guild_id=form.guild_id,
            name=f"{form.name} (копия)",
            description=form.description,
            created_by=created_by,
        )
        session.add(new_form)
        await session.flush()

        for field in form.fields:
            if not field.is_active:
                continue
            new_field = FormField(
                form_id=new_form.id,
                label=field.label,
                placeholder=field.placeholder,
                field_type=field.field_type,
                options=field.options,
                is_required=field.is_required,
                min_length=field.min_length,
                max_length=field.max_length,
                order=field.order,
                is_active=True,
            )
            session.add(new_field)

        await session.flush()
        return new_form

    @staticmethod
    async def add_field(
        session: AsyncSession,
        form: TicketForm,
        label: str,
        placeholder: Optional[str],
        field_type: str,
        is_required: bool,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        options: Optional[dict] = None,
    ) -> FormField:
        active_fields = [f for f in form.fields if f.is_active]
        if len(active_fields) >= config.MAX_FORM_FIELDS:
            raise ValueError(f"Форма не может содержать более {config.MAX_FORM_FIELDS} полей (ограничение Discord).")

        next_order = max((f.order for f in form.fields), default=-1) + 1
        field = FormField(
            form_id=form.id,
            label=label,
            placeholder=placeholder,
            field_type=field_type,
            is_required=is_required,
            min_length=min_length,
            max_length=max_length,
            options=options,
            order=next_order,
            is_active=True,
        )
        session.add(field)
        await session.flush()
        return field

    @staticmethod
    async def update_field(
        session: AsyncSession,
        field: FormField,
        label: Optional[str] = None,
        placeholder: Optional[str] = None,
        is_required: Optional[bool] = None,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        is_active: Optional[bool] = None,
    ) -> FormField:
        if label is not None:
            field.label = label
        if placeholder is not None:
            field.placeholder = placeholder if placeholder.strip() else None
        if is_required is not None:
            field.is_required = is_required
        if min_length is not None:
            field.min_length = min_length
        if max_length is not None:
            field.max_length = max_length
        if is_active is not None:
            field.is_active = is_active
        await session.flush()
        return field

    @staticmethod
    async def delete_field(session: AsyncSession, field: FormField) -> None:
        await session.delete(field)
        await session.flush()

    @staticmethod
    async def get_field_by_id(session: AsyncSession, field_id: int) -> Optional[FormField]:
        result = await session.execute(
            select(FormField).where(FormField.id == field_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def reorder_fields(
        session: AsyncSession, form: TicketForm, field_ids: list[int]
    ) -> None:
        field_map = {f.id: f for f in form.fields}
        for order, fid in enumerate(field_ids):
            if fid in field_map:
                field_map[fid].order = order
        await session.flush()
