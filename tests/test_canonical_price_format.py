from services.normalized_order_builder import NormalizedOrderBuilder


def test_regular_item_uses_canonical_two_adjacent_line_price_format():
    rendered = NormalizedOrderBuilder().format_snapshot({
        "display_name": "Аргенти",
        "quantity": 15,
        "unit": "crate",
        "cost_snapshot": {
            "factory": {"bmat": 100},
            "mpf": {"bmat": 550},
            "mpf_crates": 9,
            "resource_crate_sizes": {"bmat": 100},
        },
    })

    assert rendered == (
        "Аргенти — 15 ящиков\n\n"
        ":house: Fac - 100 BMat/[:package:1 ящ.] BMat "
        "за [:package:1 ящ.] Аргенти\n"
        ":factory: MPF - 550 BMat/[:package:6 ящ.] BMat "
        "за [:package:9 ящ.] Аргенти"
    )


def test_equipment_uses_item_factory_unit_and_mpf_crate_batch():
    rendered = NormalizedOrderBuilder().format_snapshot({
        "display_name": "Ксифос",
        "quantity": 5,
        "unit": "item",
        "cost_snapshot": {
            "factory": {"rmat": 75},
            "mpf": {"rmat": 261},
            "mpf_crates": 5,
            "resource_crate_sizes": {"rmat": 20},
        },
    })

    assert rendered == (
        "Ксифос — 5 шт.\n\n"
        ":house: Fac - 75 RMat/[:package:4 ящ.] RMat за [1 шт.] Ксифос\n"
        ":factory: MPF - 261 RMat/[:package:14 ящ.] RMat "
        "за [:package:5 ящ.] Ксифос"
    )


def test_each_resource_keeps_its_own_rounded_up_crate_count():
    rendered = NormalizedOrderBuilder().format_snapshot({
        "display_name": "Предмет",
        "quantity": 1,
        "unit": "item",
        "cost_snapshot": {
            "factory": {"bmat": 180, "rmat": 21},
            "mpf": {"bmat": 500, "rmat": 80},
            "mpf_crates": 5,
            "resource_crate_sizes": {"bmat": 100, "rmat": 20},
        },
    })

    assert (
        ":house: Fac - 180 BMat/[:package:2 ящ.] BMat + "
        "21 RMat/[:package:2 ящ.] RMat "
        "за [1 шт.] Предмет"
    ) in rendered
    assert (
        ":factory: MPF - 500 BMat/[:package:5 ящ.] BMat + "
        "80 RMat/[:package:4 ящ.] RMat "
        "за [:package:5 ящ.] Предмет"
    ) in rendered
