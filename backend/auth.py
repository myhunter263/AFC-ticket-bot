from dataclasses import dataclass
import hashlib

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from datetime import datetime, timezone
from urllib.parse import unquote

from database.crm_models import ApiCredential

bearer = HTTPBearer(auto_error=False)
ROLES = {"ADMIN", "MANAGER", "LOGISTICIAN", "PRODUCTION", "DELIVERY", "VIEWER", "BOT"}


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Principal:
    id: str
    guild_id: int
    user_id: int
    name: str
    role: str


async def authenticate(factory, token: str) -> Principal:
    async with factory() as session:
        row = await session.scalar(select(ApiCredential).where(
            ApiCredential.token_hash == token_hash(token),
            ApiCredential.revoked.is_(False),
        ))
        if row is None or (row.expires_at is not None and row.expires_at <= datetime.now(timezone.utc)):
            raise HTTPException(401, "Недействительный или отозванный токен")
        return Principal(row.id, row.guild_id, row.user_id, row.name, row.role)


async def principal(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Principal:
    if credentials is None:
        raise HTTPException(401, "Требуется авторизация", headers={"WWW-Authenticate": "Bearer"})
    actor = await authenticate(request.app.state.sessions, credentials.credentials)
    if actor.role == "BOT" and request.headers.get("X-Discord-User-Id"):
        from database.models import StaffRole
        try:
            user_id = int(request.headers["X-Discord-User-Id"])
            roles = [int(x) for x in request.headers.get("X-Discord-Roles", "").split(",") if x]
            if user_id <= 0 or len(roles) > 250:
                raise ValueError()
        except ValueError:
            raise HTTPException(422, "Некорректный Discord actor")
        async with request.app.state.sessions() as session:
            from database.crm_models import PermissionBinding
            crm_bindings = (await session.scalars(select(PermissionBinding).where(
                PermissionBinding.guild_id == actor.guild_id,
                PermissionBinding.discord_role_id.in_(roles),
            ))).all()
            bindings = (await session.scalars(select(StaffRole).where(
                StaffRole.guild_id == actor.guild_id, StaffRole.role_id.in_(roles),
                StaffRole.panel_id.is_(None),
            ))).all()
        role_types = {r.role_type for r in bindings}
        role = ("ADMIN" if "admin" in role_types else "MANAGER" if "moderator" in role_types
                else "LOGISTICIAN" if "operator" in role_types else "CUSTOMER")
        if crm_bindings:
            priority = ["ADMIN", "MANAGER", "LOGISTICIAN", "PRODUCTION", "DELIVERY", "VIEWER"]
            role = min((b.app_role for b in crm_bindings), key=priority.index)
        if request.headers.get("X-Discord-Administrator") == "true":
            role = "ADMIN"
        return Principal(actor.id, actor.guild_id, user_id,
                         unquote(request.headers.get("X-Discord-Name", str(user_id)))[:100], role)
    return actor


def require(actor: Principal, *roles: str) -> None:
    if actor.role not in roles:
        raise HTTPException(403, "Недостаточно прав")
