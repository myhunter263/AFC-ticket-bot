from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
from sqlalchemy import select

from backend.auth import Principal, principal, require
from backend.schemas import Input, VersionInput
from database.crm_models import Order
from database.operations_models import ProductionTask, Reservation, Stock, Warehouse
from services import operations as service

router = APIRouter(prefix="/api/v1", tags=["inventory and production"])


class WarehouseInput(Input):
    name: str = Field(min_length=1, max_length=100)


class StockInput(Input):
    warehouse_id: int = Field(gt=0)
    item_id: int = Field(gt=0)
    unit: Literal["item", "crate"]


class Adjustment(VersionInput):
    actual: int = Field(ge=0, le=100000000, strict=True)
    reason: str = Field(min_length=1, max_length=500)


class ReserveInput(Input):
    stock_id: int = Field(gt=0)
    order_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100000000, strict=True)
    request_key: UUID


class FinishInput(VersionInput):
    action: Literal["release", "consume"]


class TaskInput(Input):
    order_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    quantity: int = Field(gt=0, le=1000000, strict=True)
    unit: Literal["item", "crate", "batch"]
    request_key: UUID


class TaskUpdate(VersionInput):
    action: Literal["claim", "progress", "cancel"]
    completed: int | None = Field(None, ge=0, le=1000000, strict=True)


def serialize(row):
    result = {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name != "request_key"}
    if isinstance(row, Stock):
        result["available"] = row.actual - row.reserved
    return result


async def mutate(request, actor, function, *args):
    async with request.app.state.sessions() as session:
        row = await function(session, actor, *args)
        await session.commit()
        return serialize(row)


@router.get("/inventory/warehouses")
async def warehouses(request: Request, actor: Principal = Depends(principal)):
    require(actor, *service.READ)
    async with request.app.state.sessions() as session:
        return [serialize(r) for r in (await session.scalars(select(Warehouse).where(Warehouse.guild_id == actor.guild_id).order_by(Warehouse.name))).all()]


@router.post("/inventory/warehouses", status_code=201)
async def create_warehouse(value: WarehouseInput, request: Request, actor: Principal = Depends(principal)):
    return await mutate(request, actor, service.create_warehouse, value)


@router.get("/inventory/stock")
async def stock(request: Request, actor: Principal = Depends(principal), warehouse_id: int | None = None,
                search: str = Query("", max_length=200), offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200)):
    require(actor, *service.READ)
    query = select(Stock).join(Warehouse).where(Warehouse.guild_id == actor.guild_id)
    if warehouse_id:
        query = query.where(Stock.warehouse_id == warehouse_id)
    if search:
        query = query.where(Stock.name.icontains(search, autoescape=True))
    async with request.app.state.sessions() as session:
        return [serialize(r) for r in (await session.scalars(query.order_by(Stock.id).offset(offset).limit(limit))).all()]


@router.post("/inventory/stock", status_code=201)
async def create_stock(value: StockInput, request: Request, actor: Principal = Depends(principal)):
    return await mutate(request, actor, service.create_stock, value)


@router.patch("/inventory/stock/{stock_id}")
async def adjust(stock_id: int, value: Adjustment, request: Request, actor: Principal = Depends(principal)):
    return await mutate(request, actor, service.adjust, stock_id, value)


@router.get("/inventory/reservations")
async def reservations(request: Request, actor: Principal = Depends(principal), order_id: int | None = None,
                       state: Literal["ACTIVE", "RELEASED", "CONSUMED"] | None = None,
                       offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200)):
    require(actor, *service.READ)
    query = (select(Reservation, Stock.name, Stock.unit, Warehouse.name).select_from(Reservation)
        .join(Stock, Reservation.stock_id == Stock.id).join(Warehouse, Stock.warehouse_id == Warehouse.id)
        .where(Warehouse.guild_id == actor.guild_id))
    if order_id:
        query = query.where(Reservation.order_id == order_id)
    if state:
        query = query.where(Reservation.state == state)
    async with request.app.state.sessions() as session:
        rows = (await session.execute(query.order_by(Reservation.id.desc()).offset(offset).limit(limit))).all()
        return [{**serialize(r), "name": name, "unit": unit, "warehouse": warehouse} for r, name, unit, warehouse in rows]


@router.post("/inventory/reservations", status_code=201)
async def reserve(value: ReserveInput, request: Request, actor: Principal = Depends(principal)):
    return await mutate(request, actor, service.reserve, value)


@router.post("/inventory/reservations/{reservation_id}")
async def finish(reservation_id: int, value: FinishInput, request: Request, actor: Principal = Depends(principal)):
    return await mutate(request, actor, service.finish_reservation, reservation_id, value)


@router.get("/production/tasks")
async def tasks(request: Request, actor: Principal = Depends(principal), order_id: int | None = None,
                assigned_user_id: int | None = None, status: Literal["PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED"] | None = None,
                offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200)):
    require(actor, *service.READ)
    query = select(ProductionTask).join(Order).where(Order.guild_id == actor.guild_id)
    if order_id:
        query = query.where(ProductionTask.order_id == order_id)
    if assigned_user_id:
        query = query.where(ProductionTask.assigned_user_id == assigned_user_id)
    if status:
        query = query.where(ProductionTask.status == status)
    async with request.app.state.sessions() as session:
        return [serialize(r) for r in (await session.scalars(query.order_by(ProductionTask.id.desc()).offset(offset).limit(limit))).all()]


@router.post("/production/tasks", status_code=201)
async def create_task(value: TaskInput, request: Request, actor: Principal = Depends(principal)):
    return await mutate(request, actor, service.create_task, value)


@router.post("/production/tasks/{task_id}")
async def update_task(task_id: int, value: TaskUpdate, request: Request, actor: Principal = Depends(principal)):
    return await mutate(request, actor, service.update_task, task_id, value)
