from services.cost_calculators import MPFCostCalculator, ProductionCostCalculator
from services.foxhole_types import CatalogItem


def test_standard_production_supports_multiple_resources():
    item = CatalogItem(
        id=1, api_id="mixed", api_name="Mixed", ru_name="Смешанный", aliases=[],
        factory_cost={"bmat": 100, "rmat": 20},
    )
    assert ProductionCostCalculator().order_cost(item, 3) == {"bmat": 300, "rmat": 60}


def test_mpf_max_discount_batch_and_rounding():
    item = CatalogItem(
        id=1, api_id="item", api_name="Item", ru_name="Предмет", aliases=[],
        factory_cost={"bmat": 101, "rmat": 21}, mpf_available=True, mpf_max_crates=9,
    )
    cost, crates = MPFCostCalculator().reference_cost(item)
    assert crates == 9
    assert cost == {
        "bmat": sum(101 * max(50, 100 - position * 10) // 100 for position in range(1, 10)),
        "rmat": sum(21 * max(50, 100 - position * 10) // 100 for position in range(1, 10)),
    }


def test_vehicle_mpf_uses_vehicle_crates(catalog):
    bardiche = next(item for item in catalog if "bardiche" in item.api_name.casefold())
    cost, crates = MPFCostCalculator().reference_cost(bardiche)
    assert crates == 5
    assert cost == {"rmat": 1731}


def test_mpf_golden_costs_for_dusk_and_xiphos():
    calculator = MPFCostCalculator()
    assert calculator.calculate_mpf_cost({"rmat": 15}, 9) == {"rmat": 79}
    assert calculator.calculate_mpf_cost({"rmat": 75}, 5) == {"rmat": 261}
    assert [row["cost"] for row in calculator.material_breakdown(15, 9)] == [
        13, 12, 10, 9, 7, 7, 7, 7, 7,
    ]
    assert [row["cost"] for row in calculator.material_breakdown(75, 5)] == [
        67, 60, 52, 45, 37,
    ]
