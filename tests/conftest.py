from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("POSTGRES_PASSWORD", "test-password")

import pytest

from services.foxhole_types import CatalogItem
from services.item_catalog_service import SEED_ITEMS


@pytest.fixture
def catalog() -> list[CatalogItem]:
    return [
        CatalogItem(
            id=index,
            aliases=list(data["aliases"]),
            **{key: value for key, value in data.items() if key != "aliases"},
        )
        for index, data in enumerate(SEED_ITEMS, start=1)
    ]
