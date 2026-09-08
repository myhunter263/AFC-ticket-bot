"""Stock and production transactions. Lock order: order, stock, reservation/task."""
from fastapi import HTTPException
from sqlalchemy import select

from backend.auth import require
from backend.events import emit
from database.models import AuditLog, Guild
from database.operations_models import ProductionTask, Reservation, Stock, Warehouse
from services.item_catalog_service import ItemCatalogService
from services.orders.domain import TERMINAL
from services.orders.service import check_version, get_order

READ = ("ADMIN", "MANAGER", "LOGISTICIAN", "PRODUCTION", "DELIVERY", "VIEWER")
STOCK_WRITE = ("ADMIN", "MANAGER", "LOGISTICIAN")
PRODUCTION_WRITE = ("ADMIN", "MANAGER", "PRODUCTION", "LOGISTICIAN")


async def record(session, actor, kind, row, details):
    await session.flush()
    session.add(AuditLog(guild_id=actor.guild_id, user_id=actor.user_id, user_name=actor.name,
        action=kind, target_type="operations", target_id=row.id, details=details))
    await emit(session, actor.guild_id, kind, {"id": row.id, **details})


async def active_order(session, actor, order_id):
    row = await get_order(session, actor, order_id, lock=True)
    if row.status in TERMINAL:
        raise HTTPException(409, "Заказ закрыт")
    if actor.role == "LOGISTICIAN" and row.assigned_user_id not in (None, actor.user_id):
        raise HTTPException(403, "Заказ закреплён за другим логистом")
    return row


async def warehouse(session, actor, warehouse_id, *, lock=False):
    query = select(Warehouse).where(Warehouse.id == warehouse_id, Warehouse.guild_id == actor.guild_id)
    if lock:
        query = query.with_for_update()
    row = await session.scalar(query)
    if row is None:
        raise HTTPException(404, "Склад не найден")
    return row


async def stock(session, actor, stock_id, *, lock=True):
    query = select(Stock).join(Warehouse).where(Stock.id == stock_id, Warehouse.guild_id == actor.guild_id)
    if lock:
        query = query.with_for_update(of=Stock)
    row = await session.scalar(query)
    if row is None:
        raise HTTPException(404, "Остаток не найден")
    return row


async def create_warehouse(session, actor, value):
    require(actor, "ADMIN", "MANAGER")
    await session.execute(select(Guild).where(Guild.id == actor.guild_id).with_for_update())
    row = await session.scalar(select(Warehouse).where(Warehouse.guild_id == actor.guild_id, Warehouse.name == value.name))
    if row is None:
        row = Warehouse(guild_id=actor.guild_id, name=value.name)
        session.add(row)
        await record(session, actor, "inventory.warehouse_created", row, {"name": row.name})
    return row


async def create_stock(session, actor, value):
    require(actor, *STOCK_WRITE)
    await warehouse(session, actor, value.warehouse_id, lock=True)
    old = await session.scalar(select(Stock).where(Stock.warehouse_id == value.warehouse_id,
        Stock.item_id == value.item_id, Stock.unit == value.unit))
    if old:
        return old
    catalog = await ItemCatalogService.get_catalog(session, actor.guild_id)
    item = next((r for r in catalog if r.id == value.item_id), None)
    if item is None:
        raise HTTPException(422, "Предмет отсутствует в общем каталоге")
    row = Stock(warehouse_id=value.warehouse_id, item_id=item.id, name=item.ru_name, unit=value.unit)
    session.add(row)
    await record(session, actor, "inventory.stock_created", row, {"warehouse_id": row.warehouse_id, "item_id": item.id})
    return row


async def adjust(session, actor, stock_id, value):
    require(actor, *STOCK_WRITE)
    row = await stock(session, actor, stock_id)
    check_version(row, value.version)
    if value.actual < row.reserved:
        raise HTTPException(409, "Фактический остаток не может быть меньше резерва")
    before = row.actual
    row.actual, row.version = value.actual, row.version + 1
    await record(session, actor, "inventory.adjusted", row, {"before": before, "actual": row.actual, "reason": value.reason})
    return row


async def reserve(session, actor, value):
    require(actor, *STOCK_WRITE)
    await active_order(session, actor, value.order_id)
    old = await session.scalar(select(Reservation).where(Reservation.order_id == value.order_id,
        Reservation.request_key == str(value.request_key)))
    if old:
        if old.stock_id != value.stock_id or old.quantity != value.quantity:
            raise HTTPException(409, "Ключ запроса уже использован для другого резерва")
        return old
    row = await stock(session, actor, value.stock_id)
    if row.actual - row.reserved < value.quantity:
        raise HTTPException(409, "Недостаточно доступного остатка")
    row.reserved += value.quantity
    row.version += 1
    reservation = Reservation(stock_id=row.id, order_id=value.order_id, quantity=value.quantity,
        created_by=actor.user_id, request_key=str(value.request_key))
    session.add(reservation)
    await record(session, actor, "inventory.reserved", reservation, {"stock_id": row.id, "order_id": value.order_id, "quantity": value.quantity})
    return reservation


async def finish_reservation(session, actor, reservation_id, value):
    require(actor, *STOCK_WRITE, "DELIVERY")
    # Locate only within the actor's guild before acquiring the order lock.
    found = await session.scalar(select(Reservation).join(Stock).join(Warehouse).where(
        Reservation.id == reservation_id, Warehouse.guild_id == actor.guild_id))
    if found is None:
        raise HTTPException(404, "Резерв не найден")
    await active_order(session, actor, found.order_id)
    row = await stock(session, actor, found.stock_id)
    reservation = await session.scalar(select(Reservation).where(Reservation.id == reservation_id)
        .with_for_update().execution_options(populate_existing=True))
    check_version(reservation, value.version)
    if reservation.state != "ACTIVE":
        raise HTTPException(409, "Резерв уже закрыт")
    row.reserved -= reservation.quantity
    if value.action == "consume":
        row.actual -= reservation.quantity
    row.version += 1
    reservation.state = "CONSUMED" if value.action == "consume" else "RELEASED"
    reservation.version += 1
    await record(session, actor, "inventory.reservation_closed", reservation,
        {"order_id": reservation.order_id, "stock_id": row.id, "state": reservation.state, "quantity": reservation.quantity})
    return reservation


async def create_task(session, actor, value):
    require(actor, *PRODUCTION_WRITE)
    await active_order(session, actor, value.order_id)
    old = await session.scalar(select(ProductionTask).where(ProductionTask.order_id == value.order_id,
        ProductionTask.request_key == str(value.request_key)))
    if old:
        if (old.title, old.quantity, old.unit) != (value.title, value.quantity, value.unit):
            raise HTTPException(409, "Ключ запроса уже использован для другой задачи")
        return old
    row = ProductionTask(order_id=value.order_id, title=value.title, quantity=value.quantity,
        unit=value.unit, request_key=str(value.request_key))
    session.add(row)
    await record(session, actor, "production.created", row, {"order_id": row.order_id, "title": row.title, "quantity": row.quantity})
    return row


async def update_task(session, actor, task_id, value):
    from database.crm_models import Order
    require(actor, *PRODUCTION_WRITE)
    found = await session.scalar(select(ProductionTask).join(Order).where(
        ProductionTask.id == task_id, Order.guild_id == actor.guild_id))
    if found is None:
        raise HTTPException(404, "Задача не найдена")
    await active_order(session, actor, found.order_id)
    row = await session.scalar(select(ProductionTask).where(ProductionTask.id == task_id)
        .with_for_update().execution_options(populate_existing=True))
    check_version(row, value.version)
    if row.status in {"COMPLETED", "CANCELLED"}:
        raise HTTPException(409, "Задача уже закрыта")
    before = {"completed": row.completed, "status": row.status, "assigned_user_id": row.assigned_user_id}
    if value.action == "claim":
        if row.assigned_user_id is not None:
            raise HTTPException(409, "Задача уже принята")
        row.assigned_user_id, row.status = actor.user_id, "IN_PROGRESS"
    else:
        if actor.role not in {"ADMIN", "MANAGER"} and row.assigned_user_id != actor.user_id:
            raise HTTPException(403, "Сначала примите задачу; менять чужую может руководитель")
        if value.action == "cancel":
            row.status = "CANCELLED"
        else:
            if row.assigned_user_id is None:
                raise HTTPException(409, "Сначала назначьте ответственного действием «Принять»")
            if value.completed is None or not row.completed <= value.completed <= row.quantity:
                raise HTTPException(422, "Готовность должна быть между текущим значением и планом")
            row.completed = value.completed
            row.status = "COMPLETED" if row.completed == row.quantity else "IN_PROGRESS"
    row.version += 1
    await record(session, actor, "production.updated", row, {"order_id": row.order_id, "before": before,
        "completed": row.completed, "status": row.status, "assigned_user_id": row.assigned_user_id})
    return row


async def check_order_closure(session, order_id):
    if await session.scalar(select(Reservation.id).where(Reservation.order_id == order_id, Reservation.state == "ACTIVE").limit(1)):
        raise HTTPException(409, "Сначала спишите или освободите резервы заказа на складе")
    if await session.scalar(select(ProductionTask.id).where(ProductionTask.order_id == order_id,
        ProductionTask.status.in_(["PLANNED", "IN_PROGRESS"])).limit(1)):
        raise HTTPException(409, "Сначала завершите или отмените производственные задачи заказа")
