from types import SimpleNamespace

from services.calculator.aggregate import aggregate_resources
from services.calculator.factory import FactoryCalculator
from services.calculator.models import RecipeInput
from services.calculator.mpf import MPFCalculator
from services.calculator.service import CalculatorService
from services.calculator.production_chain import ProductionChainError, expand_resources
from services.foxhole_types import CatalogItem
from services.foxhole_wiki import FoxholeWikiDataProvider


def test_legacy_price_overrides_reach_shared_engine_without_mutating_source():
    item = CatalogItem(id=1, api_id="example", api_name="Example", ru_name="Example", aliases=[],
        factory_site="Garage", overrides={"factory_cost": {"rmat": 10}, "mpf_available": False},
        recipe_details={
            "garage": {"building": "Garage", "materials": {"rmat": 100}},
            "facility": {"building": "Assembly Station", "materials": {"pcon": 5}},
            "mpf": {"materials": {"rmat": 300}},
        })
    recipes = {r.key: r for r in CalculatorService.recipes(item)}
    assert recipes["garage"].materials == {"rmat": 10}
    assert recipes["garage"].source == "manual_override"
    assert recipes["facility"].materials == {"pcon": 5}
    assert "mpf" not in recipes
    assert item.recipe_details["garage"]["materials"] == {"rmat": 100}


def recipe(**values):
    defaults = dict(
        key="factory", building="Factory", kind="standard",
        output_quantity=1, output_unit="crate",
        materials={"bmat": 60, "emat": 90}, source="test",
    )
    defaults.update(values)
    return RecipeInput(**defaults)


def test_factory_multiplies_requested_crates():
    result = FactoryCalculator.calculate(
        recipe(), amount=4, calculation_unit="crate", crate_size=15
    )
    assert result.materials == {"bmat": 240, "emat": 360}
    assert result.actual_output == 4


def test_factory_converts_crates_when_recipe_outputs_individual_items():
    result = FactoryCalculator.calculate(
        recipe(output_quantity=10, output_unit="item", materials={"bmat": 5}),
        amount=4,
        calculation_unit="crate",
        crate_size=15,
    )
    assert result.batches == 6
    assert result.actual_output == 60
    assert result.materials == {"bmat": 30}


def test_factory_converts_crate_output_for_large_item_request():
    result = FactoryCalculator.calculate(
        recipe(output_quantity=1, output_unit="crate", materials={"hemat": 10}),
        amount=6,
        calculation_unit="item",
        crate_size=5,
        units_per_crate=5,
    )
    assert result.batches == 2
    assert result.actual_output == 10
    assert result.output_unit == "item"
    assert result.materials == {"hemat": 20}


def test_mpf_requested_minimum_and_reference_queue_sizes():
    mpf = recipe(key="mpf", building="Mass Production Factory", kind="mpf")
    requested = MPFCalculator.calculate(
        mpf, amount=1, calculation_unit="crate", crate_size=15,
        vehicles_per_crate=1, max_crates=9,
    )
    minimum = MPFCalculator.calculate(
        mpf, amount=3, calculation_unit="crate", crate_size=15,
        vehicles_per_crate=1, max_crates=9,
    )
    maximum = MPFCalculator.calculate(
        mpf, amount=9, calculation_unit="crate", crate_size=15,
        vehicles_per_crate=1, max_crates=9,
    )
    assert requested.queues == [3]
    assert requested.actual_output == 3
    assert minimum.materials == {"bmat": 144, "emat": 216}
    assert maximum.materials == {"bmat": 330, "emat": 495}


def test_mpf_splits_large_requests_into_valid_queues():
    assert MPFCalculator.split_queues(10, 9) == [7, 3]
    assert MPFCalculator.split_queues(11, 9) == [8, 3]
    assert MPFCalculator.split_queues(6, 5) == [3, 3]


def test_equipment_mpf_converts_units_to_transport_crates():
    result = MPFCalculator.calculate(
        recipe(key="mpf", kind="mpf", materials={"rmat": 405}),
        amount=4,
        calculation_unit="item",
        crate_size=1,
        vehicles_per_crate=3,
        max_crates=5,
    )
    assert result.queues == [3]
    assert result.actual_output == 9


def test_aggregate_combines_repeated_resources():
    one = FactoryCalculator.calculate(
        recipe(materials={"pcon": 20, "am2": 15}),
        amount=1, calculation_unit="item", crate_size=1,
    )
    two = FactoryCalculator.calculate(
        recipe(materials={"pcon": 200, "am4": 50}),
        amount=1, calculation_unit="item", crate_size=1,
    )
    assert aggregate_resources([(one, 2), (two, 1)]) == {
        "pcon": 240, "am2": 30, "am4": 50,
    }


def test_wiki_infobox_normalizes_scrap_hauler_recipe():
    text = """{{Vehicle Infobox
| codename = Harvester
| name = BMS - Scrap Hauler
| image = Harvester.png
| type = Harvester
| PRD1_Source = Small Assembly Station
| PRD1_InputItem1 = Processed Construction Materials
| PRD1_InputItem1Amount = 90
| PRD1_InputItem2 = Assembly Materials IV
| PRD1_InputItem2Amount = 25
| PRD1_OutputAmount = 1
}}"""
    fields, template = FoxholeWikiDataProvider.parse_infobox(text)
    item, recipes = FoxholeWikiDataProvider.normalize_page(
        "BMS - Scrap Hauler", fields, template, "Foxhole 1.66"
    )
    assert item["production_group"] == "equipment"
    assert recipes[0]["building"] == "Small Assembly Station"
    assert recipes[0]["materials"] == {
        "processed_construction_materials": 90,
        "assembly_materials_iv": 25,
    }


def test_manual_override_replaces_upstream_recipe():
    item = CatalogItem(
        id=1, api_id="x", api_name="X", ru_name="X", aliases=[],
        recipe_details={
            "factory": {
                "method": "factory", "building": "Factory", "recipe_kind": "standard",
                "output_quantity": 1, "output_unit": "crate",
                "materials": {"bmat": 100}, "source": "foxholehq",
            }
        },
    )
    override = SimpleNamespace(
        enabled=True, production_method="factory", building="Factory",
        materials={"bmat": 80}, output_quantity=1, output_unit="crate",
    )
    result = CalculatorService.calculate(item, 2, [override])
    assert result.methods[0].materials == {"bmat": 160}
    assert result.methods[0].source == "manual_override"


def test_service_returns_all_methods_and_handles_missing_recipe():
    item = CatalogItem(
        id=2, api_id="multi", api_name="Multi", ru_name="Multi", aliases=[],
        recipe_details={
            "factory": {
                "building": "Factory", "recipe_kind": "standard",
                "output_quantity": 1, "output_unit": "crate",
                "materials": {"bmat": 10}, "source": "foxholehq",
            },
            "facility": {
                "building": "Ammunition Factory", "recipe_kind": "facility",
                "output_quantity": 2, "output_unit": "crate",
                "materials": {"cmat": 3}, "source": "foxholewiki",
            },
        },
    )
    assert len(CalculatorService.calculate(item, 2).methods) == 2
    item.recipe_details = {}
    assert CalculatorService.calculate(item, 2).methods == []


def test_large_non_equipment_mpf_uses_item_crate_size():
    item = CatalogItem(
        id=3, api_id="shell", api_name="Shell", ru_name="Shell", aliases=[],
        production_group="item", crate_size=5, vehicle_crate_size=3,
        mpf_max_crates=9, metadata={"calculation_unit": "item"},
        recipe_details={
            "mpf": {
                "building": "Mass Production Factory", "recipe_kind": "mpf",
                "output_quantity": 1, "output_unit": "crate",
                "materials": {"hemat": 10}, "source": "foxholehq",
            }
        },
    )
    result = CalculatorService.calculate(item, 1)
    assert result.methods[0].queues == [3]
    assert result.methods[0].actual_output == 15


def test_production_chain_expands_and_detects_cycles():
    recipes = {
        "pcon": recipe(
            key="pcon", output_quantity=1, output_unit="item",
            materials={"components": 20, "cmat": 3},
        ),
        "am4": recipe(
            key="am4", output_quantity=1, output_unit="item",
            materials={"pcon": 1, "heavy_oil": 66},
        ),
    }
    assert expand_resources({"am4": 2}, recipes) == {
        "components": 40, "cmat": 6, "heavy_oil": 132,
    }
    recipes["components"] = recipe(
        key="components", output_unit="item", materials={"am4": 1}
    )
    import pytest

    with pytest.raises(ProductionChainError):
        expand_resources({"am4": 1}, recipes)


def test_shared_intermediate_rounds_after_aggregating_demand():
    recipes = {
        "a": recipe(output_quantity=1, materials={"shared": 1}),
        "b": recipe(output_quantity=1, materials={"shared": 1}),
        "shared": recipe(output_quantity=2, materials={"raw": 10}),
    }
    assert expand_resources({"a": 1, "b": 1}, recipes) == {"raw": 10}


def test_wiki_upgrade_includes_base_vehicle_and_material_output_is_uncrated():
    item, recipes = FoxholeWikiDataProvider.normalize_page("Upgrade", {
        "name": "Upgrade", "PRD1_Source": "Small Assembly Station", "PRD1_InputVehicle": "Base Tank",
        "PRD1_InputItem1": "Construction Materials", "PRD1_InputItem1Amount": "5",
    }, "Vehicle Infobox", "test")
    assert recipes[0]["materials"]["base_tank"] == 1
    _, materials = FoxholeWikiDataProvider.normalize_page("Construction Materials", {
        "name": "Construction Materials", "type": "Material", "crate_amount": "20",
        "PRD1_Source": "Materials Factory", "PRD1_InputItem1": "Salvage", "PRD1_InputItem1Amount": "10",
    }, "Item Infobox", "test")
    assert materials[0]["output_unit"] == "item"
    assert materials[0]["output_quantity"] == 1
