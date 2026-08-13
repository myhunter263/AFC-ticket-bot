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
