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
        "bmat": sum(int(101 * (1 - min(index * 0.1, 0.5))) for index in range(9)),
        "rmat": sum(int(21 * (1 - min(index * 0.1, 0.5))) for index in range(9)),
    }


def test_vehicle_mpf_uses_vehicle_crates(catalog):
    bardiche = next(item for item in catalog if item.is_vehicle)
    cost, crates = MPFCostCalculator().reference_cost(bardiche)
    assert crates == 5
    assert cost == {"rmat": 1979}
