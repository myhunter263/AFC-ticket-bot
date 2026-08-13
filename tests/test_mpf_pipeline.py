import datetime

from services.foxhole_types import CatalogItem
from services.order_preview_service import OrderPreviewService
from utils.embeds import EmbedBuilder


class _Avatar:
    url = "https://example.com/avatar.png"


class _Author:
    mention = "<@1>"
    display_avatar = _Avatar()

    def __str__(self):
        return "Tester"


def _ticket():
    return type("Ticket", (), {
        "number": 1,
        "id": 1,
        "created_at": datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        "closed_at": None,
    })()


def _item(
    api_id, api_name, ru_name, aliases, factory_cost, crates,
    is_vehicle=False, mpf_base_cost=None, production_group=None,
):
    return CatalogItem(
        id=1,
        api_id=api_id,
        api_name=api_name,
        ru_name=ru_name,
        aliases=aliases,
        is_vehicle=is_vehicle,
        production_group=production_group or ("equipment" if is_vehicle else "item"),
        factory_site="Garage" if is_vehicle else "Factory",
        factory_cost=factory_cost,
        mpf_base_cost=mpf_base_cost or factory_cost,
        mpf_available=True,
        mpf_max_crates=crates,
        vehicle_crate_size=3 if is_vehicle else 1,
        resource_crate_sizes={"rmat": 20},
    )


def _render_pipeline(text, item):
    service = OrderPreviewService([item])
    order = service.parse(text)
    assert not order.unresolved
    snapshots = service.snapshots(order)
    embed = EmbedBuilder.ticket_card(
        _ticket(), _Author(), [], "Новая", 0x123456, "", [
            {"field_label": "Заказ", "value": text, "field_type": "foxhole_order"}
        ], snapshots,
    )
    return order.items[0], snapshots[0], "\n".join(field.value for field in embed.fields)


def test_dusk_mpf_cost_survives_parser_snapshot_and_discord_embed():
    order_item, snapshot, rendered = _render_pipeline(
        "9 дасков",
        _item("foxholehq:dusk", '"Dusk" ce.III', "Даск", ["даск", "дасков"], {"rmat": 15}, 9),
    )
    assert order_item.quantity == 9
    assert order_item.unit == "crate"
    assert order_item.mpf_cost == {"rmat": 79}
    assert snapshot["cost_snapshot"]["mpf"] == {"rmat": 79}
    assert "79 RMat" in rendered
    assert "86 RMat" not in rendered


def test_xiphos_mpf_cost_survives_parser_snapshot_and_discord_embed():
    order_item, snapshot, rendered = _render_pipeline(
        "5 ксифосов",
        _item(
            "foxholehq:xiphos", 'T3 "Xiphos"', "Ксифос",
            ["ксифос", "ксифосов"], {"rmat": 25}, 5, True,
            mpf_base_cost={"rmat": 75},
        ),
    )
    assert order_item.quantity == 5
    assert order_item.unit == "item"
    assert order_item.mpf_cost == {"rmat": 261}
    assert snapshot["cost_snapshot"]["mpf"] == {"rmat": 261}
    assert "261 RMat" in rendered
    assert "25 RMat или 2 ящ RMat за шт." in rendered
    assert "261 RMat или 14 ящ RMat на MPF за 5 ящ" in rendered
    assert "264 RMat" not in rendered
