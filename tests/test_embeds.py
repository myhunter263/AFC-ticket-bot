from utils.embeds import EmbedBuilder


def test_foxhole_response_is_not_duplicated_in_regular_fields():
    responses = [
        {"field_label": "Заказ", "value": "15 аргенти", "field_type": "foxhole_order"},
        {"field_label": "Комментарий", "value": "Срочно", "field_type": "text"},
    ]

    class Avatar:
        url = "https://example.com/avatar.png"

    class Author:
        mention = "<@1>"
        display_avatar = Avatar()

        def __str__(self):
            return "Tester"

    import datetime
    ticket = type("Ticket", (), {
        "number": 1, "id": 1,
        "created_at": datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        "closed_at": None,
    })()
    embed = EmbedBuilder.ticket_card(
        ticket, Author(), [], "Новая", 0x123456, "", responses, []
    )
    names = [field.name for field in embed.fields]
    assert "Заказ" not in names
    assert "Комментарий" in names


def test_normalized_order_replaces_raw_text_in_main_ticket_embed():
    responses = [
        {"field_label": "Заказ", "value": "15 фальшионов", "field_type": "foxhole_order"},
    ]
    order_items = [{
        "display_name": "Фальшион",
        "quantity": 15,
        "unit": "item",
        "cost_snapshot": {
            "factory": {"rmat": 135},
            "factory_site": "Garage",
            "mpf": {"rmat": 1619},
            "mpf_crates": 5,
            "resource_crate_sizes": {"rmat": 20},
        },
    }]

    class Avatar:
        url = "https://example.com/avatar.png"

    class Author:
        mention = "<@1>"
        display_avatar = Avatar()

        def __str__(self):
            return "Tester"

    import datetime
    ticket = type("Ticket", (), {
        "number": 1,
        "id": 1,
        "created_at": datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        "closed_at": None,
    })()
    embed = EmbedBuilder.ticket_card(
        ticket, Author(), [], "Новая", 0x123456, "", responses, order_items
    )
    rendered = "\n".join(field.value for field in embed.fields)
    assert "15 фальшионов" not in rendered
    assert "Фальшион" in rendered
    assert "135 RMat или 7 ящиков RMat в гараже за шт." in rendered
    assert "1 619 RMat или 81 ящик RMat на MPF за 5 ящиков техники" in rendered
