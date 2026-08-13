import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models import (
    Base,
    FoxholeItem,
    FoxholeItemAlias,
    FoxholeItemLocalization,
    Guild,
    Ticket,
    TicketOrderItem,
    TicketPanel,
    TicketStatus,
)
from services.item_sync_service import ItemSyncService
from tests.test_foxholehq_provider import StaticProvider, normalized_dataset


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add(Guild(id=1, name="Test"))
        await session.commit()
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_sync_is_noop_for_same_hash_and_preserves_local_data(db_session):
    items, recipes = normalized_dataset()
    first = await ItemSyncService.sync(db_session, 1, StaticProvider(items, recipes))
    assert first.success and first.changed and first.created == 1
    localization = (await db_session.execute(select(FoxholeItemLocalization))).scalar_one()
    localization.ru_name = "Винтовка"
    localization.translation_status = "translated"
    db_session.add(FoxholeItemAlias(
        localization_id=localization.id, alias="винтарь", normalized_alias="винтарь"
    ))
    await db_session.commit()

    second = await ItemSyncService.sync(db_session, 1, StaticProvider(items, recipes))
    await db_session.commit()
    assert second.success and not second.changed
    localization = (await db_session.execute(select(FoxholeItemLocalization))).scalar_one()
    assert localization.ru_name == "Винтовка"
    assert (await db_session.execute(select(FoxholeItemAlias))).scalar_one().alias == "винтарь"


@pytest.mark.asyncio
async def test_sync_updates_cost_detects_rename_and_deactivates_removed(db_session):
    items, recipes = normalized_dataset()
    await ItemSyncService.sync(db_session, 1, StaticProvider(items, recipes))
    await db_session.commit()

    renamed_items, renamed_recipes = normalized_dataset(name="Renamed Rifle", cost=100)
    renamed = await ItemSyncService.sync(
        db_session, 1, StaticProvider(renamed_items, renamed_recipes, "hash-rename")
    )
    assert renamed.renamed == 1
    row = (await db_session.execute(select(FoxholeItem))).scalar_one()
    assert row.api_name == "Renamed Rifle"

    updated_items, updated_recipes = normalized_dataset(name="Renamed Rifle", cost=120)
    await ItemSyncService.sync(
        db_session, 1, StaticProvider(updated_items, updated_recipes, "hash-cost")
    )
    assert row.factory_cost == {"bmat": 120}

    removed = await ItemSyncService.sync(
        db_session, 1, StaticProvider([], [], "hash-empty")
    )
    assert removed.deactivated == 1
    assert not row.is_active


@pytest.mark.asyncio
async def test_ticket_snapshot_does_not_change_after_catalog_sync(db_session):
    items, recipes = normalized_dataset(cost=100)
    await ItemSyncService.sync(db_session, 1, StaticProvider(items, recipes))
    item = (await db_session.execute(select(FoxholeItem))).scalar_one()
    panel = TicketPanel(
        guild_id=1, name="Panel", category_id=1, channel_id=1, message_id=1, created_by=1
    )
    status = TicketStatus(guild_id=1, name="Open", emoji="O", color=1, order=1)
    db_session.add_all([panel, status])
    await db_session.flush()
    ticket = Ticket(
        guild_id=1, panel_id=panel.id, channel_id=1, author_id=1,
        status_id=status.id, number=1,
    )
    db_session.add(ticket)
    await db_session.flush()
    snapshot = {"factory": {"bmat": 100}, "data_version": "Patch test"}
    db_session.add(TicketOrderItem(
        ticket_id=ticket.id, item_id=item.id, quantity=1, unit="crate", query="rifle",
        display_name="Винтовка", confidence=100, matched_by="alias", cost_snapshot=snapshot,
    ))
    await db_session.commit()

    changed_items, changed_recipes = normalized_dataset(cost=120)
    await ItemSyncService.sync(
        db_session, 1, StaticProvider(changed_items, changed_recipes, "hash-cost")
    )
    order_item = (await db_session.execute(select(TicketOrderItem))).scalar_one()
    assert order_item.cost_snapshot == snapshot
