import datetime
import html

import pytest

from services.foxhole_api import FoxholeDataError, FoxholeDataset, FoxholeHQDataProvider


def _item(
    external_id: str,
    name: str,
    *,
    category: str = "small-arms",
    classes: str = "neutral",
    crate_size: int = 20,
    material: str = "bmats",
    cost: int = 100,
    methods: str = "Factory, Mass Production Factory",
) -> str:
    tooltip = (
        f'<div class="item-title-box"><span>{html.escape(name)}</span></div>'
        '<div class="item-type">Rifle</div>'
        '<div class="item-description">Stable description</div>'
        f'<span class="item-crates">crate of {crate_size}x</span>'
        f'Produced at: {methods}<'
    )
    return (
        f'<div id="{external_id}" time="37.5" {material}="{cost}" '
        f'queue="{category}" class="item {classes}" '
        f'title="{html.escape(tooltip, quote=True)}"></div>'
    )


def _page(*items: str, version: int = 65) -> str:
    return (
        f'<p>Updated to 1.{version}.x.x</p>'
        f'<div>8th July 2026 - Update FQC to Update {version}</div>'
        + "".join(items)
    )


_SCRIPT = "const crateSizes={bmats:100,rmats:20,epowders:40,hepowders:30};"


def test_provider_parses_patch_65_factory_page():
    provider = FoxholeHQDataProvider(base_url="https://example.test", min_items=2)
    dataset = provider.parse_page(
        _page(
            _item("argenti", "Argenti r.II Rifle", classes="colonial"),
            _item(
                "bardiche",
                '86K-a "Bardiche"',
                category="vehicles",
                classes="colonial mpf-only",
                crate_size=3,
                material="rmats",
                cost=495,
                methods="",
            ),
        ),
        _SCRIPT,
    )

    assert dataset.source_version == "Patch 65"
    assert dataset.source_updated_at == datetime.datetime(2026, 7, 8)
    assert len(dataset.items) == 2
    assert dataset.categories == ["small-arms", "vehicles"]
    assert dataset.resource_crate_sizes == {
        "bmat": 100,
        "rmat": 20,
        "emat": 40,
        "hemat": 30,
    }
    rifle = next(item for item in dataset.items if item["upstream_key"] == "argenti")
    assert rifle["api_id"] == "foxholehq:argenti"
    assert rifle["faction"] == "colonial"
    assert rifle["raw_data"]["time"] == 37.5


def test_provider_rejects_page_without_version_or_required_catalog_sections():
    provider = FoxholeHQDataProvider(base_url="https://example.test", min_items=1)
    with pytest.raises(FoxholeDataError, match="версию"):
        provider.parse_page(_item("argenti", "Argenti"))
    with pytest.raises(FoxholeDataError, match="целостности"):
        provider.parse_page(_page(_item("argenti", "Argenti")), _SCRIPT)


def test_provider_normalizes_vehicle_factory_and_mpf_costs():
    page = _page(
        _item(
            "bardiche",
            '86K-a "Bardiche"',
            category="vehicles",
            classes="colonial mpf-only",
            crate_size=3,
            material="rmats",
            cost=495,
            methods="",
        ),
        _item("argenti", "Argenti"),
    )
    dataset = FoxholeHQDataProvider(base_url="https://example.test", min_items=2).parse_page(
        page, _SCRIPT
    )
    tank = next(item for item in dataset.items if item["upstream_key"] == "bardiche")
    tank_recipes = [row for row in dataset.recipes if row["api_id"] == tank["api_id"]]
    assert tank["factory_cost"] == {"rmat": 165}
    assert tank["mpf_base_cost"] == {"rmat": 495}
    assert {row["production_method"] for row in tank_recipes} == {"garage", "mpf"}


class StaticProvider:
    def __init__(self, items, recipes, dataset_hash="hash-1"):
        self.dataset = FoxholeDataset(
            items=items,
            recipes=recipes,
            categories=["small-arms"],
            source_version="Patch test",
            source_updated_at=datetime.datetime(2026, 8, 13),
            dataset_hash=dataset_hash,
        )

    async def fetch_dataset(self):
        return self.dataset


def normalized_dataset(name="Rifle", cost=100):
    external_id = "".join(character for character in name.casefold() if character.isalnum())
    parser_page = _page(_item(external_id, name, cost=cost))
    # Sync-service unit tests intentionally use a small dataset and bypass provider validation.
    version, updated_at = FoxholeHQDataProvider._parse_version(parser_page)
    from services.foxhole_api import _FactoryPageParser

    parser = _FactoryPageParser()
    parser.feed(parser_page)
    return FoxholeHQDataProvider._normalize(parser.items, version, updated_at)
