import pytest

from services.foxhole_types import CatalogItem
from services.order_preview_service import OrderPreviewService


def _catalog_item(name, category, group, factory_cost, mpf_cost, aliases=None):
    return CatalogItem(
        id=hash(name), api_id=f"test:{name}", api_name=name, ru_name=name,
        aliases=aliases or [name.casefold()], category=category,
        production_group=group, is_vehicle=category == "vehicles",
        factory_cost=factory_cost, mpf_base_cost=mpf_cost, mpf_available=True,
        mpf_max_crates=5 if group == "equipment" else 9,
        resource_crate_sizes={"bmat": 100, "rmat": 20},
    )


@pytest.mark.parametrize(
    ("query", "item", "unit", "queues", "factory_unit"),
    [
        ("3 винтовки", _catalog_item("Винтовка", "small-arms", "item", {"bmat": 100}, {"bmat": 100}, ["винтовка", "винтовки"]), "crate", 9, "[:package:1 ящ.]"),
        ("3 снаряда", _catalog_item("120-мм снаряд", "heavy-ammunition", "item", {"bmat": 120}, {"bmat": 120}, ["снаряд", "снаряда"]), "crate", 9, "[:package:1 ящ.]"),
        ("3 танка", _catalog_item("Танк", "vehicles", "equipment", {"rmat": 100}, {"rmat": 300}, ["танк", "танка"]), "item", 5, "[1 шт.]"),
        ("3 контейнера", _catalog_item("Контейнер", "structures", "equipment", {"bmat": 300}, {"bmat": 300}, ["контейнер", "контейнера"]), "item", 5, "[1 шт.]"),
        ("3 орудия", _catalog_item("Орудие", "structures", "equipment", {"rmat": 105}, {"rmat": 105}, ["орудие", "орудия"]), "item", 5, "[1 шт.]"),
        ("3 стройоборудования", _catalog_item("Стройоборудование", "structures", "equipment", {"rmat": 150}, {"rmat": 150}, ["стройоборудование", "стройоборудования"]), "item", 5, "[1 шт.]"),
    ],
)
def test_production_group_controls_order_unit_queue_and_formatter(
    query, item, unit, queues, factory_unit
):
    service = OrderPreviewService([item])
    order = service.parse(query)
    assert not order.unresolved
    assert order.items[0].unit == unit
    assert order.items[0].mpf_crates == queues
    rendered = service.format_order(order)
    assert ":house: Fac - " in rendered
    assert f"за {factory_unit} {item.ru_name}" in rendered
    assert ":factory: MPF - " in rendered
    assert f"за [:package:{queues} ящ.] {item.ru_name}" in rendered


def test_compact_multi_resource_cost_groups_raw_and_crated_sides():
    item = _catalog_item(
        "Смешанная техника", "structures", "equipment",
        {"bmat": 100, "rmat": 20}, {"bmat": 100, "rmat": 20},
        ["смешанная техника"],
    )
    rendered = OrderPreviewService([item]).format_order(
        OrderPreviewService([item]).parse("1 смешанная техника")
    )
    assert (
        ":house: Fac - 100 BMat/[:package:1 ящ.] BMat + "
        "20 RMat/[:package:1 ящ.] RMat "
        "за [1 шт.] Смешанная техника"
    ) in rendered
