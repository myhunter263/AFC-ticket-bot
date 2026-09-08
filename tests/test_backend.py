import os
import secrets
import asyncio
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from backend.app import create_app
from backend.auth import token_hash
from database.crm_models import ApiCredential
from database.models import Guild


@pytest_asyncio.fixture
async def api():
    url = os.getenv("CRM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set CRM_TEST_DATABASE_URL to a migrated disposable PostgreSQL database")
    engine = create_async_engine(url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    guild_id = secrets.randbelow(10**12) + 1
    tokens = {role: secrets.token_urlsafe(32) for role in ("ADMIN", "VIEWER", "BOT", "LOGISTICIAN")}
    async with sessions() as session:
        session.add(Guild(id=guild_id, name="Integration test"))
        await session.flush()
        for index, (role, token) in enumerate(tokens.items(), 1):
            session.add(ApiCredential(guild_id=guild_id, user_id=index, name=role,
                                      role=role, token_hash=token_hash(token)))
        await session.commit()
    app = create_app(sessions)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, sessions, tokens, guild_id
    await engine.dispose()


@pytest.mark.asyncio
async def test_health_auth_and_revocation(api):
    from sqlalchemy import update
    client, sessions, tokens, guild_id = api
    assert (await client.get("/health/live")).status_code == 200
    assert (await client.get("/health/ready")).status_code == 200
    assert (await client.get("/api/v1/me")).status_code == 401
    headers = {"Authorization": f"Bearer {tokens['ADMIN']}"}
    response = await client.get("/api/v1/me", headers=headers)
    assert response.json()["guild_id"] == guild_id
    assert "token_hash" not in response.text
    async with sessions() as session:
        await session.execute(update(ApiCredential).where(ApiCredential.guild_id == guild_id).values(revoked=True))
        await session.commit()
    assert (await client.get("/api/v1/me", headers=headers)).status_code == 401


def headers(tokens, role="ADMIN"):
    return {"Authorization": f"Bearer {tokens[role]}"}


def order_payload():
    return {"idempotency_key": str(uuid.uuid4()), "delivery_location": "Westgate", "items": [
        {"name": "Delivery", "category": "delivery", "quantity": 1, "unit": "request"},
        {"name": "Escort", "category": "other", "quantity": 2, "unit": "request"},
    ]}


@pytest.mark.asyncio
async def test_date_category_filters(api):
    client, sessions, tokens, guild = api
    created = await client.post("/api/v1/orders", json=order_payload(), headers=headers(tokens))
    assert created.status_code == 201
    response = await client.get("/api/v1/orders", params={"since": "2020-01-01", "until": "2100-01-01", "category": "delivery"}, headers=headers(tokens))
    assert response.status_code == 200
    assert len(response.json()) == 1
    empty = await client.get("/api/v1/orders", params={"category": "ammunition"}, headers=headers(tokens))
    assert empty.json() == []


@pytest.mark.asyncio
async def test_create_idempotency_and_real_concurrent_assignment(api):
    client, sessions, tokens, guild = api
    payload = order_payload()
    results = await asyncio.gather(*[
        client.post("/api/v1/orders", json=payload, headers=headers(tokens)) for _ in range(2)
    ])
    assert [r.status_code for r in results] == [201, 201]
    assert results[0].json()["id"] == results[1].json()["id"]
    row = results[0].json()
    assert len(row["items"]) == 2
    assert row["status"] == "NEW"
    responses = await asyncio.gather(*[
        client.post(f"/api/v1/orders/{row['id']}/accept", json={"version": 1}, headers=headers(tokens, role))
        for role in ("ADMIN", "LOGISTICIAN")
    ])
    assert sorted(r.status_code for r in responses) == [200, 409]
    detail = (await client.get(f"/api/v1/orders/{row['id']}", headers=headers(tokens))).json()
    assert detail["version"] == 2
    assert [h["action"] for h in detail["history"]] == ["order.created", "order.assigned"]
    payload["comment"] = "Changed"
    assert (await client.post("/api/v1/orders", json=payload, headers=headers(tokens))).status_code == 409


@pytest.mark.asyncio
async def test_state_machine_permissions_and_guild_isolation(api):
    client, sessions, tokens, guild = api
    assert (await client.post("/api/v1/orders", json=order_payload(), headers=headers(tokens, "VIEWER"))).status_code == 403
    row = (await client.post("/api/v1/orders", json=order_payload(), headers=headers(tokens))).json()
    path = f"/api/v1/orders/{row['id']}"
    assert (await client.post(path + "/status", json={"version": 1, "status": "COMPLETED"}, headers=headers(tokens))).status_code == 409
    cancelled = await client.post(path + "/status", json={"version": 1, "status": "CANCELLED"}, headers=headers(tokens))
    assert cancelled.status_code == 200
    assert (await client.post(path + "/status", json={"version": 2, "status": "IN_PRODUCTION"}, headers=headers(tokens))).status_code == 409
    token = secrets.token_urlsafe(32)
    async with sessions() as session:
        other = Guild(id=guild + 10**13, name="Other")
        session.add(other)
        await session.flush()
        session.add(ApiCredential(guild_id=other.id, user_id=1, name="Other", role="ADMIN", token_hash=token_hash(token)))
        await session.commit()
    assert (await client.get(path, headers={"Authorization": f"Bearer {token}"})).status_code == 404


@pytest.mark.asyncio
async def test_catalog_units_snapshots_and_removed_item(api):
    from database.models import FoxholeItem, FoxholeItemLocalization, FoxholeProductionRecipe
    client, sessions, tokens, guild = api
    async with sessions() as session:
        item = FoxholeItem(api_id=f"test:{uuid.uuid4()}", api_name="Test Ammo", crate_size=40,
                           production_group="item", factory_cost={"bmat": 100}, is_active=True)
        session.add(item)
        await session.flush()
        session.add(FoxholeItemLocalization(guild_id=guild, item_id=item.id, ru_name="Test Ammo"))
        session.add(FoxholeProductionRecipe(item_id=item.id, production_method="factory", output_quantity=1,
                                           output_unit="crate", materials={"bmat": 100}, building="Factory"))
        await session.commit()
        item_id = item.id
    payload = order_payload()
    payload["items"] = [{"item_id": item_id, "category": "ammunition", "quantity": 10, "unit": unit} for unit in ("item", "crate")]
    response = await client.post("/api/v1/orders", json=payload, headers=headers(tokens))
    assert response.status_code == 201, response.text
    row = response.json()
    assert [i["calculation"]["methods"][0]["materials"] for i in row["items"]] == [{"bmat": 100}, {"bmat": 1000}]
    async with sessions() as session:
        original = await session.get(FoxholeItem, item_id)
        original.is_active = False
        await session.commit()
    payload["idempotency_key"] = str(uuid.uuid4())
    assert (await client.post("/api/v1/orders", json=payload, headers=headers(tokens))).status_code == 422
    saved = (await client.get(f"/api/v1/orders/{row['id']}", headers=headers(tokens))).json()
    assert saved["items"][0]["api_id"].startswith("test:")
    assert saved["items"][0]["calculation"]["methods"][0]["materials"] == {"bmat": 100}


@pytest.mark.asyncio
async def test_override_permissions_calculation_and_removal(api):
    from database.models import FoxholeItem, FoxholeItemLocalization, FoxholeProductionRecipe
    client, sessions, tokens, guild = api
    async with sessions() as session:
        item = FoxholeItem(api_id=f"test:{uuid.uuid4()}", api_name="Override test", crate_size=10, is_active=True)
        session.add(item); await session.flush()
        session.add(FoxholeItemLocalization(guild_id=guild, item_id=item.id, ru_name="Override test"))
        session.add(FoxholeProductionRecipe(item_id=item.id, production_method="factory", output_quantity=1,
            output_unit="crate", materials={"bmat": 100}, building="Factory"))
        await session.commit()
        item_id = item.id
    path = f"/api/v1/catalog/{item_id}/override"
    value = {"method": "factory", "building": "Factory", "materials": {"bmat": 20}, "output_quantity": 1, "output_unit": "crate"}
    assert (await client.put(path, json=value, headers=headers(tokens, "VIEWER"))).status_code == 403
    assert (await client.put(path, json=value, headers=headers(tokens))).status_code == 200
    calc = {"item_id": item_id, "quantity": 3, "unit": "crate"}
    response = await client.post("/api/v1/catalog/calculate", json=calc, headers=headers(tokens))
    assert response.json()["methods"][0]["materials"] == {"bmat": 60}
    assert response.json()["methods"][0]["source"] == "manual_override"
    assert len((await client.get(path + "s", headers=headers(tokens))).json()) == 1
    assert (await client.delete(path + "/factory", headers=headers(tokens))).json()["removed"]
    response = await client.post("/api/v1/catalog/calculate", json=calc, headers=headers(tokens))
    assert response.json()["methods"][0]["materials"] == {"bmat": 300}


@pytest.mark.asyncio
async def test_discord_message_restore_and_completed_job_not_retried(api):
    client, sessions, tokens, guild = api
    row = (await client.post("/api/v1/orders", json=order_payload(), headers=headers(tokens))).json()
    path = f"/api/v1/discord/messages/{row['id']}"
    ref = {"kind": "logistics", "channel_id": 123456789012345678, "message_id": 987654321098765432}
    assert (await client.put(path, json=ref, headers=headers(tokens, "BOT"))).status_code == 200
    restored = await client.get("/api/v1/discord/restore", headers=headers(tokens, "BOT"))
    assert restored.json()[0]["message_id"] == ref["message_id"]
    job = (await client.post("/api/v1/discord/jobs/claim", headers=headers(tokens, "BOT"))).json()[0]
    done = await client.post(f"/api/v1/discord/jobs/{job['id']}/complete", json={"lease": job["lease"]}, headers=headers(tokens, "BOT"))
    assert done.json()["status"] == "done"
    assert (await client.post(f"/api/v1/discord/jobs/{job['id']}/retry", headers=headers(tokens))).status_code == 409


@pytest.mark.asyncio
async def test_customer_can_only_see_own_order_and_no_notes(api):
    client, sessions, tokens, guild = api
    customer_headers = {**headers(tokens, "BOT"), "X-Discord-User-Id": "123", "X-Discord-Name": "Customer"}
    row = (await client.post("/api/v1/orders", json=order_payload(), headers=customer_headers)).json()
    path = f"/api/v1/orders/{row['id']}"
    assert (await client.post(path + "/accept", json={"version": 1}, headers=customer_headers)).status_code == 403
    await client.post(path + "/notes", json={"content": "Private"}, headers=headers(tokens))
    detail = await client.get(path, headers=customer_headers)
    assert detail.json()["notes"] == []
    assert "Private" not in detail.text
    other = {**customer_headers, "X-Discord-User-Id": "456"}
    assert (await client.get(path, headers=other)).status_code == 404
    assert (await client.post(path + "/status", json={"version": 2, "status": "CANCELLED"}, headers=customer_headers)).status_code == 200


@pytest.mark.asyncio
async def test_durable_websocket_replay(api):
    from fastapi.testclient import TestClient
    client, sessions, tokens, guild = api
    def check():
        with TestClient(create_app(sessions)) as tc:
            with tc.websocket_connect("/api/v1/events") as ws:
                ws.send_json({"token": tokens["ADMIN"], "after": 0})
                assert ws.receive_json()["type"] == "connected"
                response = tc.post("/api/v1/orders", json=order_payload(), headers=headers(tokens))
                assert response.status_code == 201
                event = ws.receive_json()
                assert event["type"] == "order.created"
                assert event["payload"]["order_id"] == response.json()["id"]
            with tc.websocket_connect("/api/v1/events") as ws:
                ws.send_json({"token": tokens["VIEWER"], "after": event["id"] - 1})
                assert ws.receive_json()["type"] == "connected"
                assert ws.receive_json()["id"] == event["id"]
    await asyncio.to_thread(check)


@pytest.mark.asyncio
async def test_jobs_leases_and_retry(api):
    client, sessions, tokens, guild = api
    await client.post("/api/v1/orders", json=order_payload(), headers=headers(tokens))
    path = "/api/v1/discord/jobs"
    claims = await asyncio.gather(*[client.post(path + "/claim", headers=headers(tokens, "BOT")) for _ in range(2)])
    assert sorted(len(r.json()) for r in claims) == [0, 1]
    job = next(r.json()[0] for r in claims if r.json())
    response = await client.post(f"{path}/{job['id']}/complete", json={"lease": "wrong"}, headers=headers(tokens, "BOT"))
    assert response.status_code == 409
    response = await client.post(f"{path}/{job['id']}/complete", json={"lease": job["lease"], "error": "Closed DM"}, headers=headers(tokens, "BOT"))
    assert response.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_role_binding_and_expired_credentials(api):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    client, sessions, tokens, guild = api
    response = await client.put("/api/v1/permissions", json={"discord_role_id": 999, "app_role": "LOGISTICIAN"}, headers=headers(tokens))
    assert response.status_code == 200
    delegated = {**headers(tokens, "BOT"), "X-Discord-User-Id": "777", "X-Discord-Roles": "999"}
    assert (await client.get("/api/v1/me", headers=delegated)).json()["role"] == "LOGISTICIAN"
    # Untrusted ordinary API clients cannot impersonate another Discord member.
    spoofed = {**headers(tokens, "VIEWER"), "X-Discord-User-Id": "777", "X-Discord-Administrator": "true"}
    assert (await client.get("/api/v1/me", headers=spoofed)).json()["role"] == "VIEWER"
    async with sessions() as session:
        await session.execute(update(ApiCredential).where(ApiCredential.token_hash == token_hash(tokens["VIEWER"])).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        await session.commit()
    assert (await client.get("/api/v1/me", headers=headers(tokens, "VIEWER"))).status_code == 401


@pytest.mark.asyncio
async def test_admin_override_requires_reason_and_stale_edits_conflict(api):
    client, sessions, tokens, guild = api
    payload = order_payload()
    row = (await client.post("/api/v1/orders", json=payload, headers=headers(tokens))).json()
    path = f"/api/v1/orders/{row['id']}"
    await client.post(path + "/status", json={"version": 1, "status": "CANCELLED"}, headers=headers(tokens))
    change = {"version": 2, "status": "NEW", "admin_override": True}
    assert (await client.post(path + "/status", json=change, headers=headers(tokens))).status_code == 422
    change["reason"] = "Reopened by customer request"
    assert (await client.post(path + "/status", json=change, headers=headers(tokens))).status_code == 200
    edit = {"version": 2, "items": payload["items"], "delivery_location": "Other"}
    assert (await client.patch(path, json=edit, headers=headers(tokens))).status_code == 409


@pytest.mark.asyncio
async def test_invalid_quantities_and_item_references_are_rejected(api):
    client, sessions, tokens, guild = api
    for quantity in (0, -1, 100001, True, 1.5):
        payload = order_payload()
        payload["items"][0]["quantity"] = quantity
        assert (await client.post("/api/v1/orders", json=payload, headers=headers(tokens))).status_code == 422
    payload = order_payload()
    payload["items"][0] = {"item_id": 2147483640, "category": "vehicle", "quantity": 1, "unit": "item"}
    assert (await client.post("/api/v1/orders", json=payload, headers=headers(tokens))).status_code == 422
