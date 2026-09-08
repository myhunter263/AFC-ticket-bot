from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select, update

from backend.auth import Principal, principal, require
from database.crm_models import ApiCredential, Order, OrderSettings
from database.models import AuditLog
from services.item_sync_service import ItemSyncService
from backend.schemas import Input
from pydantic import Field
from typing import Literal
from database.crm_models import PermissionBinding

router = APIRouter(prefix="/api/v1", tags=["administration"])


class BindingInput(Input):
    discord_role_id: int = Field(gt=0)
    app_role: Literal["ADMIN", "MANAGER", "LOGISTICIAN", "PRODUCTION", "DELIVERY", "VIEWER"]


@router.get("/permissions")
async def permissions(request: Request, actor: Principal = Depends(principal)):
    require(actor, "ADMIN", "MANAGER")
    async with request.app.state.sessions() as session:
        rows = (await session.scalars(select(PermissionBinding).where(PermissionBinding.guild_id == actor.guild_id))).all()
        return [{"id": r.id, "discord_role_id": r.discord_role_id, "app_role": r.app_role} for r in rows]


@router.put("/permissions")
async def bind(value: BindingInput, request: Request, actor: Principal = Depends(principal)):
    from backend.discord import settings_row
    require(actor, "ADMIN")
    async with request.app.state.sessions() as session:
        await settings_row(session, actor.guild_id)
        row = await session.scalar(select(PermissionBinding).where(PermissionBinding.guild_id == actor.guild_id, PermissionBinding.discord_role_id == value.discord_role_id))
        if row is None:
            row = PermissionBinding(guild_id=actor.guild_id, discord_role_id=value.discord_role_id)
            session.add(row)
        row.app_role = value.app_role
        session.add(AuditLog(guild_id=actor.guild_id, user_id=actor.user_id, user_name=actor.name,
                            action="permissions.updated", target_type="discord_role", target_id=value.discord_role_id, details={"role": value.app_role}))
        await session.commit()
        return {"saved": True}


@router.delete("/permissions/{binding_id}")
async def unbind(binding_id: int, request: Request, actor: Principal = Depends(principal)):
    from sqlalchemy import delete
    require(actor, "ADMIN")
    async with request.app.state.sessions() as session:
        result = await session.execute(delete(PermissionBinding).where(PermissionBinding.id == binding_id, PermissionBinding.guild_id == actor.guild_id))
        await session.commit()
        return {"removed": result.rowcount > 0}


@router.get("/dashboard")
async def dashboard(request: Request, actor: Principal = Depends(principal)):
    require(actor, "ADMIN", "MANAGER", "LOGISTICIAN", "PRODUCTION", "DELIVERY", "VIEWER")
    async with request.app.state.sessions() as session:
        counts = dict((await session.execute(select(Order.status, func.count()).where(Order.guild_id == actor.guild_id).group_by(Order.status))).all())
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        completed = await session.scalar(select(func.count()).select_from(Order).where(Order.guild_id == actor.guild_id, Order.completed_at >= today))
        settings = await session.get(OrderSettings, actor.guild_id)
        sync = await ItemSyncService.status(session, actor.guild_id)
        return {"counts": counts, "completed_today": completed, "backend": "ok", "database": "ok",
                "bot_last_seen": settings.bot_last_seen if settings else None, "catalog": sync}


@router.get("/users")
async def users(request: Request, actor: Principal = Depends(principal)):
    require(actor, "ADMIN", "MANAGER")
    async with request.app.state.sessions() as session:
        rows = (await session.scalars(select(ApiCredential).where(ApiCredential.guild_id == actor.guild_id))).all()
        return [{"id": r.id, "user_id": r.user_id, "name": r.name, "role": r.role, "revoked": r.revoked} for r in rows]


@router.post("/users/{credential_id}/revoke")
async def revoke(credential_id: str, request: Request, actor: Principal = Depends(principal)):
    require(actor, "ADMIN")
    if credential_id == actor.id:
        raise HTTPException(409, "Отзыв текущего токена выполняется через серверную команду")
    async with request.app.state.sessions() as session:
        result = await session.execute(update(ApiCredential).where(ApiCredential.id == credential_id, ApiCredential.guild_id == actor.guild_id).values(revoked=True))
        await session.commit()
        return {"revoked": result.rowcount > 0}


@router.get("/logs")
async def logs(request: Request, actor: Principal = Depends(principal)):
    require(actor, "ADMIN", "MANAGER")
    async with request.app.state.sessions() as session:
        rows = (await session.scalars(select(AuditLog).where(AuditLog.guild_id == actor.guild_id).order_by(AuditLog.id.desc()).limit(200))).all()
        return [{"at": r.created_at, "actor": r.user_name, "action": r.action, "target": r.target_id} for r in rows]
