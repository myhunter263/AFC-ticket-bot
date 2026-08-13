from services.foxhole_types import ResolvedItem
from services.item_resolver import ItemResolver


def test_resolves_russian_aliases_typos_and_api_name(catalog):
    resolver = ItemResolver(catalog)
    expected = {
        "аргенти": "Аргенти",
        "аргеннти": "Аргенти",
        "ARGENTI": "Аргенти",
        "бердыш": "Бардиш",
        "бердышей": "Бардиш",
        "бардич": "Бардиш",
        "762": "Патроны 7.62 мм",
        "7.62": "Патроны 7.62 мм",
        "7 62": "Патроны 7.62 мм",
    }
    for query, name in expected.items():
        result = resolver.resolve(query)
        assert isinstance(result, ResolvedItem), query
        assert result.item.ru_name == name, query


def test_low_confidence_returns_candidates(catalog):
    result = ItemResolver(catalog).resolve("совершенно неизвестный предмет")
    assert not isinstance(result, ResolvedItem)
