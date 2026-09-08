from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import logging

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from backend.auth import require
from database.crm_models import Order, OrderItem
from database.models import AuditLog, Guild, FoxholeRecipeOverride
from services.calculator.service import CalculatorService
from services.item_catalog_service import ItemCatalogService
from services.orders.domain import Status, TERMINAL, TRANSITIONS


async def get_order(session, actor, order_id, *, lock=False):
    query = select(Order).where(Order.id == order_id, Order.guild_id == actor.guild_id).options(selectinload(Order.items))
    if actor.role == "CUSTOMER":
        query = query.where(Order.discord_user_id == actor.user_id)
    if lock:
        query = query.with_for_update()
    order = await session.scalar(query)
    if order is None:
        raise HTTPException(404, "Заказ не найден")
    return order


def check_version(order, version):
    if order.version != version:
        raise HTTPException(409, "Заказ уже изменён. Обновите карточку")


async def record(session, order, actor, action, details=None):
    logging.getLogger(__name__).info("%s order=%s guild=%s actor=%s version=%s", action, order.id, actor.guild_id, actor.user_id, order.version)
    session.add(AuditLog(guild_id=actor.guild_id, user_id=actor.user_id,
                        user_name=actor.name, action=action, target_type="order",
                        target_id=order.id, details=details or {}))
    from backend.events import emit
    from database.crm_models import IntegrationJob
    payload = {"order_id": order.id, "version": order.version, "status": order.status,
               "assigned_user_id": order.assigned_user_id}
    await emit(session, actor.guild_id, action, payload)
    if action != "order.note_added":
        session.add(IntegrationJob(guild_id=actor.guild_id, kind="order_message", payload=payload))
    if action in {"order.created", "order.assigned", "order.status_changed"}:
        session.add(IntegrationJob(guild_id=actor.guild_id, kind="customer_notice", payload=payload))


async def build_items(session, actor, inputs):
    catalog = {row.id: row for row in await ItemCatalogService.get_catalog(session, actor.guild_id)}
    override_rows = (await session.scalars(select(FoxholeRecipeOverride).where(
        FoxholeRecipeOverride.guild_id == actor.guild_id,
    ))).all()
    items = []
    for position, value in enumerate(inputs):
        item = catalog.get(value.item_id)
        if value.item_id is not None and item is None:
            raise HTTPException(422, "Предмет удалён или недоступен в каталоге")
        calculation = {}
        if item:
            overrides = [r for r in override_rows if r.item_id == item.id]
            if value.unit == "batch":
                recipe = next((r for r in CalculatorService.recipes(item, overrides) if r.key == value.recipe_key), None)
                if recipe is None or recipe.kind == "mpf" or recipe.key == "mpf":
                    raise HTTPException(422, "Для MPF укажите ящики; для партии выберите действующий обычный рецепт")
                calculation = {"batch_recipe": asdict(recipe), "materials": {
                    k: v * value.quantity for k, v in recipe.materials.items()
                }, "actual_output": recipe.output_quantity * value.quantity, "output_unit": recipe.output_unit}
            else:
                from services.calculator.planning import calculate_plan
                calculation = calculate_plan(item, value.quantity, list(catalog.values()), override_rows, unit=value.unit)
            calculation["source_version"] = item.source_version
            calculation["crate_size"] = item.crate_size
        items.append(OrderItem(
            item_id=value.item_id, api_id_snapshot=item.api_id if item else None,
            name_snapshot=item.ru_name if item else value.name, category=value.category,
            position=position, quantity=value.quantity, unit=value.unit,
            comment=value.comment, calculation=calculation,
        ))
    return items


async def create_order(session, actor, value):
    require(actor, "CUSTOMER", "ADMIN", "MANAGER", "LOGISTICIAN", "PRODUCTION", "DELIVERY")
    digest = hashlib.sha256(json.dumps(value.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    # Serialize numbering and duplicate confirmations within a guild, in PostgreSQL.
    guild = await session.scalar(select(Guild).where(Guild.id == actor.guild_id).with_for_update())
    if guild is None:
        raise HTTPException(404, "Сервер не настроен")
    old = await session.scalar(select(Order).where(
        Order.guild_id == actor.guild_id, Order.discord_user_id == actor.user_id,
        Order.idempotency_key == str(value.idempotency_key),
    ).options(selectinload(Order.items)))
    if old:
        if old.request_hash != digest:
            raise HTTPException(409, "Ключ подтверждения уже использован для другого состава")
        return old
    number = (await session.scalar(select(func.max(Order.public_number)).where(Order.guild_id == actor.guild_id)) or 0) + 1
    order = Order(guild_id=actor.guild_id, public_number=number, discord_user_id=actor.user_id,
                  customer_name=actor.name, status="NEW", delivery_location=value.delivery_location,
                  comment=value.comment, idempotency_key=str(value.idempotency_key), request_hash=digest,
                  items=await build_items(session, actor, value.items))
    session.add(order)
    await session.flush()
    await record(session, order, actor, "order.created")
    return order


async def accept_order(session, actor, order_id, version):
    require(actor, "ADMIN", "MANAGER", "LOGISTICIAN")
    order = await get_order(session, actor, order_id, lock=True)
    check_version(order, version)
    if order.status != Status.NEW or order.assigned_user_id is not None:
        raise HTTPException(409, "Заказ уже принят или больше недоступен")
    order.assigned_user_id = actor.user_id
    order.status = Status.ACCEPTED
    order.version += 1
    order.updated_at = datetime.now(timezone.utc)
    await record(session, order, actor, "order.assigned", {"old_status": "NEW", "status": "ACCEPTED", "assigned_user_id": actor.user_id})
    return order


async def transition(session, actor, order_id, value):
    order = await get_order(session, actor, order_id, lock=True)
    check_version(order, value.version)
    if actor.role == "CUSTOMER":
        if value.status != Status.CANCELLED or order.status != Status.NEW:
            raise HTTPException(403, "Самостоятельно отменить можно только новый заказ")
    else:
        require(actor, "ADMIN", "MANAGER", "LOGISTICIAN", "PRODUCTION", "DELIVERY")
        if actor.role == "LOGISTICIAN" and order.assigned_user_id not in {None, actor.user_id}:
            raise HTTPException(403, "Заказ закреплён за другим логистом")
        if actor.role == "PRODUCTION" and value.status not in {Status.WAITING_RESOURCES, Status.IN_PRODUCTION, Status.READY}:
            raise HTTPException(403, "Переход недоступен производству")
        if actor.role == "DELIVERY" and value.status not in {Status.IN_DELIVERY, Status.COMPLETED}:
            raise HTTPException(403, "Переход недоступен доставке")
    if value.admin_override:
        require(actor, "ADMIN")
        if not value.reason:
            raise HTTPException(422, "Для административного перехода нужна причина")
    elif value.status not in TRANSITIONS.get(Status(order.status), set()):
        raise HTTPException(409, "Недопустимый переход статуса")
    if value.status == Status.ACCEPTED and order.assigned_user_id is None:
        raise HTTPException(409, "Используйте действие «Принять» для назначения ответственного")
    old = order.status
    if value.status in TERMINAL:
        from services.operations import check_order_closure
        await check_order_closure(session, order.id)
    order.status = value.status
    if value.status == Status.NEW:
        order.assigned_user_id = None
    order.version += 1
    order.updated_at = datetime.now(timezone.utc)
    order.completed_at = order.updated_at if value.status == Status.COMPLETED else None
    await record(session, order, actor, "order.status_changed", {
        "old_status": old, "status": value.status, "reason": value.reason,
        "admin_override": value.admin_override,
    })
    return order


async def edit_order(session, actor, order_id, value):
    require(actor, "ADMIN", "MANAGER", "LOGISTICIAN")
    order = await get_order(session, actor, order_id, lock=True)
    check_version(order, value.version)
    if order.status in TERMINAL:
        raise HTTPException(409, "Закрытый заказ нельзя редактировать")
    if actor.role == "LOGISTICIAN" and order.assigned_user_id not in {None, actor.user_id}:
        raise HTTPException(403, "Заказ закреплён за другим логистом")
    before = {"items": [{"name": i.name_snapshot, "quantity": i.quantity, "unit": i.unit} for i in order.items],
              "delivery_location": order.delivery_location, "comment": order.comment}
    order.items = await build_items(session, actor, value.items)
    order.delivery_location, order.comment = value.delivery_location, value.comment
    order.version += 1
    order.updated_at = datetime.now(timezone.utc)
    await record(session, order, actor, "order.updated", {"before": before, "after": value.model_dump(mode="json")})
    return order
