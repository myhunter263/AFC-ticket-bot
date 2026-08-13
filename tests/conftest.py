from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("POSTGRES_PASSWORD", "test-password")

import pytest

from services.foxhole_types import CatalogItem
from services.item_catalog_service import SEED_ITEMS


@pytest.fixture
def catalog() -> list[CatalogItem]:
    vehicle_ids = {
        "foxholehq:falchion", "foxholehq:bardiche", "foxholehq:hatchet",
        "foxholehq:devittmk3", "foxholehq:silverhand", "foxholehq:scorpion",
        "foxholehq:r1hauler", "foxholehq:flatbed", "foxholehq:crane",
        "foxholehq:ironship",
    }
    return [
        CatalogItem(
            id=index,
            aliases=list(data["aliases"]),
            alias_metadata={
                alias: {
                    "alias_type": data.get("alias_type", "seed"),
                    "priority": data.get("priority", 100),
                }
                for alias in data["aliases"]
            },
            is_vehicle=data["api_id"] in vehicle_ids,
            crate_size=3 if data["api_id"] in vehicle_ids else 1,
            vehicle_crate_size=3 if data["api_id"] in vehicle_ids else 1,
            factory_site="Garage" if data["api_id"] in vehicle_ids else "Factory",
            factory_cost=(
                {"rmat": 165} if "bardiche" in data["api_name"].casefold()
                else {"rmat": 135} if "falchion" in data["api_name"].casefold()
                else {"bmat": 100}
            ),
            mpf_available=True,
            mpf_max_crates=5 if data["api_id"] in vehicle_ids else 9,
            resource_crate_sizes={"bmat": 100, "rmat": 20, "emat": 40, "hemat": 30},
            **{
                key: value
                for key, value in data.items()
                if key not in {
                    "aliases", "alias_type", "priority", "category",
                }
            },
        )
        for index, data in enumerate(SEED_ITEMS, start=1)
    ]
