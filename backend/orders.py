from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import String, cast, or_, select

from backend.auth import Principal, principal, require
from backend.schemas import EditInput, NoteInput, OrderInput, TransitionInput, VersionInput
from database.crm_models import Order, OrderItem, OrderNote
from database.models import AuditLog
from services.orders import service
from services.orders.domain import LABELS, Status

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


def serialize(order):
    return {
        "id": order.id, "public_number": order.public_number, "guild_id": order.guild_id,
        "discord_user_id": order.discord_user_id, "customer_name": order.customer_name,
        "status": order.status, "status_label": LABELS[Status(order.status)],
        "assigned_user_id": order.assigned_user_id, "version": order.version,
        "delivery_location": order.delivery_location, "comment": order.comment,
        "created_at": order.created_at, "updated_at": order.updated_at, "completed_at": order.completed_at,
        "items": [{"id": i.id, "item_id": i.item_id, "api_id": i.api_id_snapshot,
                   "name": i.name_snapshot, "category": i.category, "quantity": i.quantity,
                   "unit": i.unit, "comment": i.comment, "calculation": i.calculation} for i in order.items],
    }


def readable(actor):
    require(actor, "ADMIN", "MANAGER", "LOGISTICIAN", "PRODUCTION", "DELIVERY", "VIEWER", "CUSTOMER", "BOT")


@router.post("", status_code=201)
async def create(value: OrderInput, request: Request, actor: Principal = Depends(principal)):
    async with request.app.state.sessions() as session:
        row = await service.create_order(session, actor, value)
        await session.commit()
        return serialize(row)


@router.get("")
async def listing(request: Request, actor: Principal = Depends(principal),
                  status: Status | None = None, assigned_user_id: int | None = None,
                  customer_id: int | None = None, search: str = Query("", max_length=200),
                  category: str | None = None, since: datetime | None = None, until: datetime | None = None,
                  offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200)):
    from sqlalchemy.orm import selectinload
    readable(actor)
    query = select(Order).where(Order.guild_id == actor.guild_id).options(selectinload(Order.items))
    if actor.role == "CUSTOMER":
        query = query.where(Order.discord_user_id == actor.user_id)
    if status:
        query = query.where(Order.status == status)
    if assigned_user_id is not None:
        query = query.where(Order.assigned_user_id == assigned_user_id)
    if customer_id is not None:
        query = query.where(Order.discord_user_id == customer_id)
    if since:
        since = since.replace(tzinfo=timezone.utc) if since.tzinfo is None else since
        query = query.where(Order.created_at >= since)
    if until:
        until = until.replace(tzinfo=timezone.utc) if until.tzinfo is None else until
        query = query.where(Order.created_at < until)
    if category:
        query = query.where(Order.items.any(OrderItem.category == category))
    if search:
        query = query.where(or_(cast(Order.public_number, String).contains(search, autoescape=True),
                               Order.items.any(OrderItem.name_snapshot.icontains(search, autoescape=True))))
    async with request.app.state.sessions() as session:
        rows = (await session.scalars(query.order_by(Order.id.desc()).offset(offset).limit(limit))).all()
        return [serialize(row) for row in rows]


@router.get("/{order_id}")
async def detail(order_id: int, request: Request, actor: Principal = Depends(principal)):
    readable(actor)
    async with request.app.state.sessions() as session:
        row = await service.get_order(session, actor, order_id)
        result = serialize(row)
        history = (await session.scalars(select(AuditLog).where(
            AuditLog.guild_id == actor.guild_id, AuditLog.target_type == "order", AuditLog.target_id == order_id,
        ).order_by(AuditLog.id))).all()
        result["history"] = [{"action": h.action, "actor": h.user_name, "at": h.created_at,
                              "details": h.details} for h in history if actor.role != "CUSTOMER" or h.action in {
                                  "order.created", "order.assigned", "order.status_changed"}]
        result["notes"] = []
        if actor.role != "CUSTOMER":
            notes = (await session.scalars(select(OrderNote).where(OrderNote.order_id == order_id).order_by(OrderNote.id))).all()
            result["notes"] = [{"author": n.author_name, "content": n.content, "at": n.created_at} for n in notes]
        return result


@router.post("/{order_id}/accept")
async def accept(order_id: int, value: VersionInput, request: Request, actor: Principal = Depends(principal)):
    async with request.app.state.sessions() as session:
        row = await service.accept_order(session, actor, order_id, value.version)
        await session.commit()
        return serialize(row)


@router.post("/{order_id}/status")
async def status_change(order_id: int, value: TransitionInput, request: Request, actor: Principal = Depends(principal)):
    async with request.app.state.sessions() as session:
        row = await service.transition(session, actor, order_id, value)
        await session.commit()
        return serialize(row)


@router.patch("/{order_id}")
async def edit(order_id: int, value: EditInput, request: Request, actor: Principal = Depends(principal)):
    async with request.app.state.sessions() as session:
        row = await service.edit_order(session, actor, order_id, value)
        await session.commit()
        return serialize(row)


@router.post("/{order_id}/notes", status_code=201)
async def note(order_id: int, value: NoteInput, request: Request, actor: Principal = Depends(principal)):
    require(actor, "ADMIN", "MANAGER", "LOGISTICIAN", "PRODUCTION", "DELIVERY")
    async with request.app.state.sessions() as session:
        row = await service.get_order(session, actor, order_id, lock=True)
        session.add(OrderNote(order_id=row.id, author_id=actor.user_id, author_name=actor.name, content=value.content))
        row.version += 1
        from datetime import timezone
        row.updated_at = datetime.now(timezone.utc)
        await service.record(session, row, actor, "order.note_added")
        await session.commit()
        return {"version": row.version}
