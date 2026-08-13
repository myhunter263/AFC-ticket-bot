from services.foxhole_types import ResolvedItem
from services.item_resolver import ItemResolver
from services.foxhole_types import CatalogItem


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
        "фальшионов": "Фальшион",
        "фальшев": "Фальшион",
    }
    for query, name in expected.items():
        result = resolver.resolve(query)
        assert isinstance(result, ResolvedItem), query
        assert result.item.ru_name == name, query


def test_low_confidence_returns_candidates(catalog):
    result = ItemResolver(catalog).resolve("совершенно неизвестный предмет")
    assert not isinstance(result, ResolvedItem)


def test_seeded_core_slang_is_exact(catalog):
    resolver = ItemResolver(catalog)
    expected = {
        "биматы": "Биматы",
        "рматы": "Рматы",
        "ематы": "Ематы",
        "хематы": "Хематы",
        "бинты": "Бинты",
        "рубашки": "Рубашки",
        "даск": "Даск",
        "даска": "Даск",
        "гидра": "Гидра",
        "гидры": "Гидра",
        "тремолы": "Тремола",
        "лунайр": "Лунайр",
    }
    for query, ru_name in expected.items():
        result = resolver.resolve(query)
        assert isinstance(result, ResolvedItem)
        assert result.item.ru_name == ru_name
        assert result.confidence == 100
        assert result.matched_by == "exact_alias"


def test_required_acceptance_aliases_never_use_fuzzy_fallback(catalog):
    resolver = ItemResolver(catalog)
    for query in (
        "даск", "даска", "гидра", "гидры", "биматы", "бинты", "рубашки",
        "рматы", "ематы", "хематы", "аргенти", "фальш", "бердыш",
        "тремолы", "лунайр", "762",
    ):
        result = resolver.resolve(query)
        assert isinstance(result, ResolvedItem), query
        assert result.confidence == 100, query
        assert result.matched_by == "exact_alias", query


def test_exact_database_alias_has_priority_and_debug_metadata():
    item = CatalogItem(
        id=1,
        api_id="db-item",
        api_name="Database Item",
        ru_name="Предмет",
        aliases=["тестовыйжаргон"],
        alias_metadata={
            "тестовыйжаргон": {"alias_type": "custom", "priority": 150}
        },
    )
    resolver = ItemResolver([item])
    result = resolver.resolve("  ТЕСТОВЫЙЖАРГОН ")
    assert isinstance(result, ResolvedItem)
    assert result.confidence == 100
    assert result.matched_by == "exact_alias"
    assert resolver.debug("тестовыйжаргон")["source"] == "database_alias"
    assert resolver.debug("тестовыйжаргон")["normalized"] == "тестовыйжаргон"
