import asyncio

import asyncpg
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from backend.auth import authenticate
from database.crm_models import OutboxEvent

router = APIRouter()


async def emit(session, guild_id, kind, payload):
    # Per-guild commit ordering prevents cursors skipping an uncommitted earlier event.
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"crm-events:{guild_id}"})
    row = OutboxEvent(guild_id=guild_id, kind=kind, payload=payload)
    session.add(row)
    await session.flush()
    await session.execute(text("SELECT pg_notify('crm_events', :guild)"), {"guild": str(guild_id)})
    return row


@router.websocket("/api/v1/events")
async def events(websocket: WebSocket):
    await websocket.accept()
    connection = None
    try:
        # Auth frame avoids putting credentials in URLs/access logs.
        hello = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        if not isinstance(hello, dict) or not isinstance(hello.get("token"), str):
            raise HTTPException(401, "Неверный формат авторизации")
        token = hello.get("token", "")
        actor = await authenticate(websocket.app.state.sessions, token)
        if actor.role not in {"ADMIN", "MANAGER", "LOGISTICIAN", "PRODUCTION", "DELIVERY", "VIEWER", "BOT"}:
            raise HTTPException(403, "Нет доступа")
        cursor = max(0, int(hello.get("after", 0)))
        async with websocket.app.state.sessions() as session:
            url = session.bind.url.set(drivername="postgresql")
        connection = await asyncpg.connect(url.render_as_string(hide_password=False))
        wake = asyncio.Event()

        def notified(conn, pid, channel, payload):
            if payload == str(actor.guild_id):
                wake.set()

        await connection.add_listener("crm_events", notified)
        await websocket.send_json({"type": "connected"})
        while True:
            wake.clear()
            actor = await authenticate(websocket.app.state.sessions, token)
            async with websocket.app.state.sessions() as session:
                rows = (await session.scalars(select(OutboxEvent).where(
                    OutboxEvent.guild_id == actor.guild_id, OutboxEvent.id > cursor,
                ).order_by(OutboxEvent.id).limit(200))).all()
            for row in rows:
                await websocket.send_json({"id": row.id, "type": row.kind, "payload": row.payload})
                cursor = row.id
            if len(rows) == 200:
                continue
            try:
                await asyncio.wait_for(wake.wait(), timeout=20)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "heartbeat", "after": cursor})
    except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError, ValueError, TypeError, HTTPException, asyncpg.PostgresError, SQLAlchemyError, OSError):
        try:
            await websocket.close(code=1008)
        except RuntimeError:
            pass
    finally:
        if connection:
            await connection.close()
