import pytest

from services.order_parser import OrderParser
from services.order_preview_service import OrderPreviewService


@pytest.mark.parametrize(
    ("text", "quantity", "unit", "query"),
    [
        ("15 ящиков аргенти", 15, "crate", "аргенти"),
        ("15 ящ 762", 15, "crate", "7.62"),
        ("5 бердышей", 5, None, "бердышей"),
    ],
)
def test_parser(text, quantity, unit, query):
    line = OrderParser().parse(text)[0]
    assert (line.quantity, line.requested_unit, line.query) == (quantity, unit, query)


def test_units_come_from_catalog(catalog):
    order = OrderPreviewService(catalog).parse(
        "15 ящиков аргенти\n15 ящиков 762\n5 бердышей"
    )
    assert [item.unit for item in order.items] == ["crate", "crate", "item"]
    assert not order.unresolved


def test_free_form_single_line(catalog):
    order = OrderPreviewService(catalog).parse(
        "Нужно 15 ящиков аргенти, столько же патронов 762 и ещё 5 бердышей"
    )
    assert [item.quantity for item in order.items] == [15, 15, 5]
    assert [item.resolved.item.ru_name for item in order.items] == [
        "Аргенти", "Патроны 7.62 мм", "Бардиш",
    ]


def test_quantity_after_item_name(catalog):
    order = OrderPreviewService(catalog).parse("бердыши 5")
    assert len(order.items) == 1
    assert order.items[0].quantity == 5
    assert order.items[0].resolved.item.ru_name == "Бардиш"


@pytest.mark.parametrize(
    ("text", "quantities", "names"),
    [
        ("15 фальшионов", [15], ["Фальшион"]),
        ("15 фальшев", [15], ["Фальшион"]),
        ("15 аргентей", [15], ["Аргенти"]),
        (
            "15 фальшионов\n20 аргентей\n30 762",
            [15, 20, 30],
            ["Фальшион", "Аргенти", "Патроны 7.62 мм"],
        ),
        (
            "Нужно 15 фальшионов и ещё 20 ящиков аргенти",
            [15, 20],
            ["Фальшион", "Аргенти"],
        ),
        (
            "дайте 5 бердышей, 15 аргентей и патронов 762 ящиков 20",
            [5, 15, 20],
            ["Бардиш", "Аргенти", "Патроны 7.62 мм"],
        ),
        (
            "заказ:\nфальшионы 15\nаргенти 20\n762 30",
            [15, 20, 30],
            ["Фальшион", "Аргенти", "Патроны 7.62 мм"],
        ),
    ],
)
def test_acceptance_free_form_orders(catalog, text, quantities, names):
    order = OrderPreviewService(catalog).parse(text)
    assert not order.unresolved
    assert [item.quantity for item in order.items] == quantities
    assert [item.resolved.item.ru_name for item in order.items] == names


def test_units_are_normalized_even_when_user_omits_or_misstates_them(catalog):
    order = OrderPreviewService(catalog).parse("15 ящиков фальшионов\n15 аргенти")
    assert [item.unit for item in order.items] == ["item", "crate"]
