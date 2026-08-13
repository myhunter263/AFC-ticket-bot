import datetime
import hashlib
import json

import pytest

from services.foxhole_api import FoxholeDataError, FoxholeDataset, FoxholeHQDataProvider


def _bundle(items: dict) -> str:
    # Minimal unobfuscated equivalent of the actual FoxholeHQ iteminfo contract.
    source = repr(items)
    strings = [row["name"] for row in items.values()]
    for index, name in enumerate(strings):
        source = source.replace(
            "'name': " + repr(name),
            "'name': " + f"_0x362918({hex(0x194 + index)})",
            1,
        )
    encoded = ",".join(repr(value) for value in strings)
    return (
        f"const iteminfo={source};function _0x221e(){{var _0x5c45f0=[{encoded}]"
        ";_0x221e=function(){return _0x5c45f0;};return _0x221e();}"
    )


def test_provider_parses_structured_iteminfo_without_executing_javascript():
    raw = {
        f"Rifle {index}": {
            "name": f"Rifle {index}", "type": "Rifle", "desc": "Stable description",
            "ammo": "7.62mm", "produces": "20x per crate",
            "bmat": 100, "rmat": 0, "emat": 0, "hemat": 0,
        }
        for index in range(12)
    }
    parsed = FoxholeHQDataProvider._parse_iteminfo(_bundle(raw))
    assert parsed == raw


def test_provider_rejects_changed_or_damaged_bundle():
    with pytest.raises(FoxholeDataError, match="iteminfo"):
        FoxholeHQDataProvider._parse_iteminfo("const something_else = {}")


def test_provider_normalizes_vehicle_factory_and_mpf_costs():
    raw = {
        "Tank": {
            "name": "Tank", "type": "Tank", "desc": "Tank description", "ammo": "40mm",
            "produces": "3x per crate", "bmat": 0, "rmat": 495, "emat": 0, "hemat": 0,
        }
    }
    items, recipes = FoxholeHQDataProvider._normalize(
        raw,
        {"Tank": {"category": "vehicles", "faction": "neutral"}},
        "Patch test",
        datetime.datetime(2026, 8, 13),
    )
    assert items[0]["factory_cost"] == {"rmat": 165}
    assert items[0]["mpf_base_cost"] == {"rmat": 495}
    assert {row["production_method"] for row in recipes} == {"garage", "mpf"}


class StaticProvider:
    def __init__(self, items, recipes, dataset_hash="hash-1"):
        self.dataset = FoxholeDataset(
            items=items,
            recipes=recipes,
            categories=["smallarms"],
            source_version="Patch test",
            source_updated_at=datetime.datetime(2026, 8, 13),
            dataset_hash=dataset_hash,
        )

    async def fetch_dataset(self):
        return self.dataset


def normalized_dataset(name="Rifle", cost=100):
    raw = {
        name: {
            "name": name, "type": "Rifle", "desc": "Stable description", "ammo": "7.62mm",
            "produces": "20x per crate", "bmat": cost, "rmat": 0, "emat": 0, "hemat": 0,
        }
    }
    return FoxholeHQDataProvider._normalize(
        raw,
        {name: {"category": "smallarms", "faction": "neutral"}},
        "Patch test",
        datetime.datetime(2026, 8, 13),
    )
