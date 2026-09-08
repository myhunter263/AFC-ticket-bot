import asyncio
import uuid

import pytest

from test_backend import api as backend_api, headers, order_payload
from database.models import FoxholeItem, FoxholeItemLocalization

api = backend_api  # Shared disposable PostgreSQL fixture.


async def setup_stock(api, actual=100):
    client, sessions, tokens, guild = api
    async with sessions() as session:
        item = FoxholeItem(api_id=f"stock-test:{uuid.uuid4()}", api_name="40mm", crate_size=40, is_active=True)
        session.add(item); await session.flush()
        session.add(FoxholeItemLocalization(guild_id=guild, item_id=item.id, ru_name="40mm"))
        await session.commit()
        item_id = item.id
    warehouse = await client.post("/api/v1/inventory/warehouses", json={"name": "Stockpile A"}, headers=headers(tokens))
    assert warehouse.status_code == 201
    stock = await client.post("/api/v1/inventory/stock", json={"warehouse_id": warehouse.json()["id"], "item_id": item_id, "unit": "crate"}, headers=headers(tokens))
    assert stock.status_code == 201
    stock_id = stock.json()["id"]
    adjusted = await client.patch(f"/api/v1/inventory/stock/{stock_id}", json={"actual": actual, "version": 1, "reason": "Initial count"}, headers=headers(tokens))
    assert adjusted.status_code == 200
    order = (await client.post("/api/v1/orders", json=order_payload(), headers=headers(tokens))).json()
    return stock_id, order["id"]


@pytest.mark.asyncio
async def test_concurrent_reservations_cannot_overbook_and_retry_is_idempotent(api):
    stock_id, order_id = await setup_stock(api)
    client, _, tokens, _ = api
    requests = [{"stock_id": stock_id, "order_id": order_id, "quantity": 70, "request_key": str(uuid.uuid4())} for _ in range(2)]
    other_order = (await client.post("/api/v1/orders", json=order_payload(), headers=headers(tokens))).json()
    requests[1]["order_id"] = other_order["id"]
    responses = await asyncio.gather(*[client.post("/api/v1/inventory/reservations", json=r, headers=headers(tokens)) for r in requests])
    assert sorted(r.status_code for r in responses) == [201, 409]
    index = next(i for i, r in enumerate(responses) if r.status_code == 201)
    retry = await client.post("/api/v1/inventory/reservations", json=requests[index], headers=headers(tokens))
    assert retry.json()["id"] == responses[index].json()["id"]
    stock = (await client.get("/api/v1/inventory/stock", headers=headers(tokens))).json()[0]
    assert (stock["actual"], stock["reserved"], stock["available"]) == (100, 70, 30)
    listed = await client.get("/api/v1/inventory/reservations", params={"state": "ACTIVE"}, headers=headers(tokens))
    assert listed.status_code == 200
    assert listed.json()[0]["warehouse"] == "Stockpile A"
    assert listed.json()[0]["quantity"] == 70
    changed = {**requests[index], "quantity": 1}
    assert (await client.post("/api/v1/inventory/reservations", json=changed, headers=headers(tokens))).status_code == 409


@pytest.mark.asyncio
async def test_reservation_consume_release_versions_and_order_closure(api):
    stock_id, order_id = await setup_stock(api)
    client, _, tokens, _ = api
    payload = {"stock_id": stock_id, "order_id": order_id, "quantity": 30, "request_key": str(uuid.uuid4())}
    reservation = (await client.post("/api/v1/inventory/reservations", json=payload, headers=headers(tokens))).json()
    denied = await client.post(f"/api/v1/orders/{order_id}/status", json={"version": 1, "status": "CANCELLED"}, headers=headers(tokens))
    assert denied.status_code == 409
    adjust = await client.patch(f"/api/v1/inventory/stock/{stock_id}", json={"version": 3, "actual": 10, "reason": "Count"}, headers=headers(tokens))
    assert adjust.status_code == 409
    path = f"/api/v1/inventory/reservations/{reservation['id']}"
    results = await asyncio.gather(*[client.post(path, json={"version": 1, "action": "consume"}, headers=headers(tokens)) for _ in range(2)])
    assert sorted(r.status_code for r in results) == [200, 409]
    stock = (await client.get("/api/v1/inventory/stock", headers=headers(tokens))).json()[0]
    assert (stock["actual"], stock["reserved"], stock["available"]) == (70, 0, 70)
    payload["request_key"] = str(uuid.uuid4())
    reservation = (await client.post("/api/v1/inventory/reservations", json=payload, headers=headers(tokens))).json()
    await client.post(f"/api/v1/inventory/reservations/{reservation['id']}", json={"version": 1, "action": "release"}, headers=headers(tokens))
    assert (await client.post(f"/api/v1/orders/{order_id}/status", json={"version": 1, "status": "CANCELLED"}, headers=headers(tokens))).status_code == 200
    payload["request_key"] = str(uuid.uuid4())
    assert (await client.post("/api/v1/inventory/reservations", json=payload, headers=headers(tokens))).status_code == 409


@pytest.mark.asyncio
async def test_stock_permissions_and_guild_isolation(api):
    stock_id, order_id = await setup_stock(api)
    client, sessions, tokens, guild = api
    from database.models import Guild
    from database.crm_models import ApiCredential
    from backend.auth import token_hash
    async with sessions() as session:
        other = Guild(id=guild + 10**13, name="Other")
        session.add(other); await session.flush()
        session.add(ApiCredential(guild_id=other.id, user_id=12, name="Other", role="ADMIN", token_hash=token_hash(str(guild))))
        await session.commit()
    value = {"version": 2, "actual": 1, "reason": "Count"}
    assert (await client.patch(f"/api/v1/inventory/stock/{stock_id}", json=value, headers=headers(tokens, "VIEWER"))).status_code == 403
    other_headers = {"Authorization": f"Bearer {guild}"}
    assert (await client.patch(f"/api/v1/inventory/stock/{stock_id}", json=value, headers=other_headers)).status_code == 404
    assert (await client.get("/api/v1/inventory/stock", headers=other_headers)).json() == []
    assert (await client.get("/api/v1/inventory/stock", headers=headers(tokens, "BOT"))).status_code == 403


@pytest.mark.asyncio
async def test_concurrent_counts_and_units_stay_separate(api):
    stock_id, order_id = await setup_stock(api)
    client, _, tokens, _ = api
    results = await asyncio.gather(*[client.patch(f"/api/v1/inventory/stock/{stock_id}", json={"actual": n, "version": 2, "reason": "Count"}, headers=headers(tokens)) for n in (90, 120)])
    assert sorted(r.status_code for r in results) == [200, 409]
    row = (await client.get("/api/v1/inventory/stock", headers=headers(tokens))).json()[0]
    single = await client.post("/api/v1/inventory/stock", json={"warehouse_id": row["warehouse_id"], "item_id": row["item_id"], "unit": "item"}, headers=headers(tokens))
    assert single.status_code == 201
    assert single.json()["actual"] == 0
    assert single.json()["id"] != stock_id
    assert row["actual"] in (90, 120)


@pytest.mark.asyncio
async def test_production_cannot_change_another_workers_task(api):
    from database.crm_models import ApiCredential
    from backend.auth import token_hash
    client, sessions, tokens, guild = api
    token = str(uuid.uuid4())
    async with sessions() as session:
        session.add(ApiCredential(guild_id=guild, user_id=50, name="Production", role="PRODUCTION", token_hash=token_hash(token)))
        await session.commit()
    order = (await client.post("/api/v1/orders", json=order_payload(), headers=headers(tokens))).json()
    value = {"order_id": order["id"], "title": "Falchion", "quantity": 5, "unit": "item", "request_key": str(uuid.uuid4())}
    task = (await client.post("/api/v1/production/tasks", json=value, headers=headers(tokens))).json()
    path = f"/api/v1/production/tasks/{task['id']}"
    assert (await client.post(path, json={"action": "claim", "version": 1}, headers=headers(tokens))).status_code == 200
    other_headers = {"Authorization": f"Bearer {token}"}
    assert (await client.post(path, json={"action": "progress", "completed": 3, "version": 2}, headers=other_headers)).status_code == 403
    assert (await client.post(path, json={"action": "cancel", "version": 2}, headers=headers(tokens))).json()["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_production_assignment_progress_closure_and_events(api):
    client, sessions, tokens, guild = api
    order = (await client.post("/api/v1/orders", json=order_payload(), headers=headers(tokens))).json()
    value = {"order_id": order["id"], "title": "Upgrade Spatha", "quantity": 5, "unit": "item", "request_key": str(uuid.uuid4())}
    task = (await client.post("/api/v1/production/tasks", json=value, headers=headers(tokens))).json()
    retry = (await client.post("/api/v1/production/tasks", json=value, headers=headers(tokens))).json()
    assert task["id"] == retry["id"]
    path = f"/api/v1/production/tasks/{task['id']}"
    results = await asyncio.gather(*[client.post(path, json={"version": 1, "action": "claim"}, headers=headers(tokens, r)) for r in ("ADMIN", "LOGISTICIAN")])
    assert sorted(r.status_code for r in results) == [200, 409]
    assert (await client.post(path, json={"version": 2, "action": "progress", "completed": 6}, headers=headers(tokens))).status_code == 422
    denied = await client.post(f"/api/v1/orders/{order['id']}/status", json={"version": 1, "status": "CANCELLED"}, headers=headers(tokens))
    assert denied.status_code == 409
    progress = await client.post(path, json={"version": 2, "action": "progress", "completed": 2}, headers=headers(tokens))
    assert progress.json()["completed"] == 2
    done = await client.post(path, json={"version": 3, "action": "progress", "completed": 5}, headers=headers(tokens))
    assert done.json()["status"] == "COMPLETED"
    assert (await client.post(path, json={"version": 4, "action": "claim"}, headers=headers(tokens))).status_code == 409
    assert (await client.post(f"/api/v1/orders/{order['id']}/status", json={"version": 1, "status": "CANCELLED"}, headers=headers(tokens))).status_code == 200
    from sqlalchemy import select
    from database.crm_models import OutboxEvent
    async with sessions() as session:
        events = (await session.scalars(select(OutboxEvent).where(OutboxEvent.guild_id == guild, OutboxEvent.kind == "production.updated"))).all()
        assert len(events) == 3
        assert events[-1].payload["completed"] == 5
