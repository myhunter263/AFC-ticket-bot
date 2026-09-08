from datetime import datetime, timedelta, timezone
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import or_, select

from backend.auth import Principal, principal, require
from backend.events import emit
from backend.schemas import Input
from database.crm_models import IntegrationJob, OrderDiscordMessage, OrderSettings
from database.models import Guild
from services.orders.service import get_order

router = APIRouter(prefix="/api/v1/discord", tags=["discord"])


@router.get("/restore")
async def restore(request: Request, actor: Principal = Depends(principal)):
    from database.crm_models import Order
    require(actor, "BOT")
    async with request.app.state.sessions() as session:
        rows = (await session.scalars(select(OrderDiscordMessage).join(Order).where(
            Order.guild_id == actor.guild_id, OrderDiscordMessage.kind == "logistics",
        ))).all()
        return [{"order_id": r.order_id, "message_id": r.message_id} for r in rows]


async def settings_row(session, guild_id):
    await session.execute(select(Guild).where(Guild.id == guild_id).with_for_update())
    row = await session.get(OrderSettings, guild_id)
    if row is None:
        row = OrderSettings(guild_id=guild_id)
        session.add(row)
        await session.flush()
    return row


def settings_dict(row):
    return {c.name: getattr(row, c.name) for c in OrderSettings.__table__.columns}


class SettingsInput(Input):
    panel_channel_id: int | None = Field(None, gt=0)
    logistics_channel_id: int | None = Field(None, gt=0)
    fallback_category_id: int | None = Field(None, gt=0)
    panel_title: str = Field("Логистический центр", min_length=1, max_length=100)
    panel_description: str = Field("Оставьте заявку на технику, припасы или доставку.", max_length=2000)


@router.get("/settings")
async def settings(request: Request, actor: Principal = Depends(principal)):
    require(actor, "ADMIN", "MANAGER", "BOT")
    async with request.app.state.sessions() as session:
        row = await settings_row(session, actor.guild_id)
        await session.commit()
        return settings_dict(row)


@router.put("/settings")
async def save_settings(value: SettingsInput, request: Request, actor: Principal = Depends(principal)):
    require(actor, "ADMIN")
    async with request.app.state.sessions() as session:
        row = await settings_row(session, actor.guild_id)
        if row.panel_channel_id != value.panel_channel_id:
            row.panel_message_id = None
        for key, val in value.model_dump().items():
            setattr(row, key, val)
        await emit(session, actor.guild_id, "discord.settings_updated", {})
        await session.commit()
        return settings_dict(row)


@router.post("/panel", status_code=202)
async def publish(request: Request, actor: Principal = Depends(principal)):
    require(actor, "ADMIN")
    async with request.app.state.sessions() as session:
        row = await settings_row(session, actor.guild_id)
        if not row.panel_channel_id or not row.logistics_channel_id:
            raise HTTPException(422, "Настройте канал панели и канал логистов")
        job = IntegrationJob(guild_id=actor.guild_id, kind="panel", payload={})
        session.add(job)
        await emit(session, actor.guild_id, "discord.panel_requested", {})
        await session.commit()
        return {"job_id": job.id}


@router.get("/jobs")
async def jobs(request: Request, actor: Principal = Depends(principal)):
    require(actor, "ADMIN", "MANAGER", "BOT")
    async with request.app.state.sessions() as session:
        rows = (await session.scalars(select(IntegrationJob).where(IntegrationJob.guild_id == actor.guild_id).order_by(IntegrationJob.id.desc()).limit(100))).all()
        return [{"id": r.id, "kind": r.kind, "status": r.status, "attempts": r.attempts, "error": r.last_error} for r in rows]


@router.post("/jobs/claim")
async def claim(request: Request, actor: Principal = Depends(principal)):
    require(actor, "BOT")
    now = datetime.now(timezone.utc)
    async with request.app.state.sessions() as session:
        settings = await settings_row(session, actor.guild_id)
        settings.bot_last_seen = now
        # One leased job per guild preserves message update ordering across workers.
        busy = await session.scalar(select(IntegrationJob.id).where(
            IntegrationJob.guild_id == actor.guild_id, IntegrationJob.status == "running",
            IntegrationJob.locked_until > now,
        ).limit(1))
        if busy is not None:
            await session.commit()
            return []
        row = await session.scalar(select(IntegrationJob).where(
            IntegrationJob.guild_id == actor.guild_id,
            or_((IntegrationJob.status == "pending") & (IntegrationJob.available_at <= now),
                (IntegrationJob.status == "running") & (IntegrationJob.locked_until <= now)),
        ).order_by(IntegrationJob.id).with_for_update(skip_locked=True).limit(1))
        if row is None:
            await session.commit()
            return []
        row.status, row.lease = "running", str(uuid.uuid4())
        row.locked_until = now + timedelta(minutes=5)
        row.attempts += 1
        await session.commit()
        return [{"id": row.id, "kind": row.kind, "payload": row.payload, "lease": row.lease}]


class JobResult(Input):
    lease: str
    error: str | None = Field(None, max_length=1000)


@router.post("/jobs/{job_id}/complete")
async def complete(job_id: int, value: JobResult, request: Request, actor: Principal = Depends(principal)):
    require(actor, "BOT")
    async with request.app.state.sessions() as session:
        row = await session.scalar(select(IntegrationJob).where(IntegrationJob.id == job_id, IntegrationJob.guild_id == actor.guild_id).with_for_update())
        if row is None:
            raise HTTPException(404, "Задание не найдено")
        if row.status != "running" or row.lease != value.lease:
            raise HTTPException(409, "Аренда задания истекла")
        row.last_error = value.error
        row.status = "pending" if value.error and row.attempts < 5 else "failed" if value.error else "done"
        row.available_at = datetime.now(timezone.utc) + timedelta(seconds=min(300, 10 * 2 ** row.attempts))
        await session.commit()
        return {"status": row.status}


@router.post("/jobs/{job_id}/retry")
async def retry(job_id: int, request: Request, actor: Principal = Depends(principal)):
    require(actor, "ADMIN")
    async with request.app.state.sessions() as session:
        row = await session.scalar(select(IntegrationJob).where(IntegrationJob.id == job_id, IntegrationJob.guild_id == actor.guild_id).with_for_update())
        if row is None or row.status not in {"failed", "pending"}:
            raise HTTPException(409, "Повторить можно только неотправленное задание")
        row.status, row.attempts = "pending", 0
        row.available_at = datetime.now(timezone.utc)
        await emit(session, actor.guild_id, "discord.retry_requested", {"job_id": row.id})
        await session.commit()
        return {"status": "pending"}


class MessageInput(Input):
    kind: Literal["logistics", "fallback", "panel"]
    channel_id: int = Field(gt=0)
    message_id: int | None = Field(None, gt=0)


@router.get("/messages/{order_id}")
async def messages(order_id: int, request: Request, actor: Principal = Depends(principal)):
    require(actor, "BOT")
    async with request.app.state.sessions() as session:
        await get_order(session, actor, order_id)
        rows = (await session.scalars(select(OrderDiscordMessage).where(OrderDiscordMessage.order_id == order_id))).all()
        return [{"kind": r.kind, "channel_id": r.channel_id, "message_id": r.message_id} for r in rows]


@router.put("/messages/{order_id}")
async def save_message(order_id: int, value: MessageInput, request: Request, actor: Principal = Depends(principal)):
    require(actor, "BOT")
    async with request.app.state.sessions() as session:
        if value.kind == "panel":
            row = await settings_row(session, actor.guild_id)
            if value.channel_id != row.panel_channel_id:
                raise HTTPException(409, "Канал панели изменился")
            row.panel_message_id = value.message_id
        else:
            await get_order(session, actor, order_id, lock=True)
            row = await session.scalar(select(OrderDiscordMessage).where(OrderDiscordMessage.order_id == order_id, OrderDiscordMessage.kind == value.kind))
            if row is None:
                row = OrderDiscordMessage(order_id=order_id, kind=value.kind)
                session.add(row)
            row.channel_id, row.message_id = value.channel_id, value.message_id
        await session.commit()
        return {"saved": True}
