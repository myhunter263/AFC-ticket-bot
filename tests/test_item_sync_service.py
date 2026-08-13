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
from services.item_catalog_service import ItemCatalogService
from services.item_resolver import ItemResolver
from services.foxhole_types import ResolvedItem
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
async def test_source_id_change_preserves_translation_and_alias(db_session):
    items, recipes = normalized_dataset(name="Argenti r.II Rifle")
    items[0]["api_id"] = "foxholehq:argenti-r-ii-rifle"
    recipes[0]["api_id"] = items[0]["api_id"]
    if len(recipes) > 1:
        recipes[1]["api_id"] = items[0]["api_id"]
    await ItemSyncService.sync(db_session, 1, StaticProvider(items, recipes, "legacy-source"))

    localization = (await db_session.execute(select(FoxholeItemLocalization))).scalar_one()
    localization.ru_name = "Аргенти"
    localization.translation_status = "translated"
    db_session.add(FoxholeItemAlias(
        localization_id=localization.id,
        alias="аргенти",
        normalized_alias="аргенти",
    ))
    await db_session.commit()

    current_items, current_recipes = normalized_dataset(name="Argenti r.II Rifle")
    current_items[0]["api_id"] = "foxholehq:argenti"
    for recipe in current_recipes:
        recipe["api_id"] = "foxholehq:argenti"
    result = await ItemSyncService.sync(
        db_session,
        1,
        StaticProvider(current_items, current_recipes, "current-source"),
    )
    await db_session.commit()

    item = (await db_session.execute(select(FoxholeItem))).scalar_one()
    localization = (await db_session.execute(select(FoxholeItemLocalization))).scalar_one()
    alias = (await db_session.execute(select(FoxholeItemAlias))).scalar_one()
    assert result.created == 0
    assert item.api_id == "foxholehq:argenti"
    assert localization.ru_name == "Аргенти"
    assert alias.alias == "аргенти"


@pytest.mark.asyncio
async def test_seed_aliases_are_deduplicated_after_normalization(db_session):
    items = []
    recipes = []
    for name, category, item_type, cost, crate_size in (
        ("Argenti r.II Rifle", "smallarms", "Rifle", {"bmat": 100}, 20),
        ("7.62mm", "smallarms", "Ammunition", {"bmat": 80}, 40),
        ("86K-a 'Bardiche'", "vehicles", "Tank", {"rmat": 495}, 3),
    ):
        normalized_items, normalized_recipes = normalized_dataset(name=name)
        normalized_items[0]["category"] = category
        normalized_items[0]["is_vehicle"] = category == "vehicles"
        normalized_items[0]["crate_size"] = crate_size
        normalized_items[0]["vehicle_crate_size"] = crate_size if category == "vehicles" else 1
        normalized_items[0]["factory_cost"] = (
            {"rmat": 165} if category == "vehicles" else cost
        )
        normalized_items[0]["raw_data"]["type"] = item_type
        if category == "vehicles":
            for recipe in normalized_recipes:
                if recipe["production_method"] != "mpf":
                    recipe["production_method"] = "garage"
                    recipe["output_quantity"] = 1
                    recipe["output_unit"] = "vehicle"
                    recipe["materials"] = {"rmat": 165}
                elif recipe["production_method"] == "mpf":
                    recipe["output_quantity"] = 1
                    recipe["output_unit"] = "vehicle_crate"
                    recipe["materials"] = {"rmat": 495}
                    recipe["raw_data"] = {"vehicles_per_crate": crate_size}
        items.extend(normalized_items)
        recipes.extend(normalized_recipes)

    await ItemSyncService.sync(db_session, 1, StaticProvider(items, recipes, "seed-hash"))
    await ItemCatalogService.ensure_seed(db_session, 1)
    await db_session.commit()

    aliases = list((await db_session.execute(select(FoxholeItemAlias))).scalars().all())
    keys = [(alias.localization_id, alias.normalized_alias) for alias in aliases]
    assert len(keys) == len(set(keys))
    assert sum(alias.normalized_alias == "7.62" for alias in aliases) == 1


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


@pytest.mark.asyncio
async def test_new_database_alias_is_visible_without_bot_restart(db_session):
    items, recipes = normalized_dataset(name="Database Rifle")
    await ItemSyncService.sync(db_session, 1, StaticProvider(items, recipes, "db-alias"))
    await db_session.commit()

    first_catalog = await ItemCatalogService.get_catalog(db_session, 1)
    assert not isinstance(ItemResolver(first_catalog).resolve("тестовыйжаргон"), ResolvedItem)

    localization = (await db_session.execute(select(FoxholeItemLocalization))).scalar_one()
    await ItemCatalogService.add_alias(
        db_session,
        localization,
        "  ТЕСТОВЫЙЖАРГОН ",
        created_by=42,
        alias_type="slang",
        priority=150,
    )
    await db_session.commit()

    refreshed_catalog = await ItemCatalogService.get_catalog(db_session, 1)
    result = ItemResolver(refreshed_catalog).resolve("тестовыйжаргон")
    assert isinstance(result, ResolvedItem)
    assert result.item.api_name == "Database Rifle"
    assert result.confidence == 100
    assert result.matched_by == "exact_alias"


@pytest.mark.asyncio
async def test_seed_layers_deduplicate_pending_alias_with_autoflush_disabled(db_session):
    item = FoxholeItem(api_id="foxholehq:aalto", api_name="Aalto Storm Rifle 24")
    db_session.add(item)
    await db_session.flush()
    localization = FoxholeItemLocalization(
        guild_id=1,
        item_id=item.id,
        ru_name="Аалто",
        translation_status="translated",
    )
    db_session.add(localization)
    await db_session.flush()

    await ItemCatalogService._upsert_seed_aliases(
        db_session, localization, ["аалто"], "auto_transliteration", 70
    )
    await ItemCatalogService._upsert_seed_aliases(
        db_session, localization, ["аалто"], "transliteration", 105
    )
    await db_session.flush()

    aliases = list((await db_session.execute(
        select(FoxholeItemAlias).where(
            FoxholeItemAlias.localization_id == localization.id
        )
    )).scalars().all())
    assert len(aliases) == 1
    assert aliases[0].normalized_alias == "аалто"
    assert aliases[0].alias_type == "transliteration"
    assert aliases[0].priority == 105
