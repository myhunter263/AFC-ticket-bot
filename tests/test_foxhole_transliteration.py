from services.foxhole_transliteration import (
    automatic_transliterations,
    transliterate_english,
)


def test_transliterates_full_names_and_distinctive_tokens():
    aliases = automatic_transliterations("KLG901-2 Lunaire F")
    assert "лунайре" in aliases
    assert transliterate_english("Dusk") == "дуск"
    assert transliterate_english("Hydra") == "хидра"


def test_manual_dictionary_remains_responsible_for_game_specific_pronunciation():
    aliases = automatic_transliterations('85K-b "Falchion"')
    assert "фалчион" in aliases
