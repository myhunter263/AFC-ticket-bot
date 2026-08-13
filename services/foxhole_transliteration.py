from __future__ import annotations

import re

from services.text_normalizer import TextNormalizer


_DIGRAPHS = {
    "sch": "ск", "sh": "ш", "ch": "ч", "th": "т", "ph": "ф",
    "ck": "к", "qu": "кв", "ee": "и", "oo": "у", "ai": "ай",
    "ay": "ай", "oi": "ой", "oy": "ой", "ou": "ау", "ow": "ау",
}
_LETTERS = {
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф",
    "g": "г", "h": "х", "i": "и", "j": "дж", "k": "к", "l": "л",
    "m": "м", "n": "н", "o": "о", "p": "п", "q": "к", "r": "р",
    "s": "с", "t": "т", "u": "у", "v": "в", "w": "в", "x": "кс",
    "y": "и", "z": "з",
}
_GENERIC_WORDS = {
    "anti", "aircraft", "ammo", "ambulance", "auto", "automatic", "cannon",
    "charge", "class", "equipment", "field", "flame", "fragmentation", "grenade",
    "gun", "gunship", "heavy", "infantry", "launcher", "machine", "materials",
    "mobile", "model", "mortar", "rifle", "rocket", "shell", "storm", "submachine",
    "supplies", "tank", "tanker", "transport", "universal", "vehicle",
}


def transliterate_english(value: str) -> str:
    source = value.casefold()
    output: list[str] = []
    index = 0
    while index < len(source):
        char = source[index]
        if not ("a" <= char <= "z"):
            output.append(char)
            index += 1
            continue
        matched = False
        for size in (3, 2):
            chunk = source[index:index + size]
            if chunk in _DIGRAPHS:
                output.append(_DIGRAPHS[chunk])
                index += size
                matched = True
                break
        if not matched:
            output.append(_LETTERS.get(char, char))
            index += 1
    return TextNormalizer.normalize("".join(output), remove_service_words=False)


def automatic_transliterations(api_name: str) -> list[str]:
    aliases: list[str] = []
    full = transliterate_english(api_name)
    if full:
        aliases.append(full)
    for token in re.findall(r"[A-Za-z]{4,}", api_name):
        if token.casefold() in _GENERIC_WORDS:
            continue
        alias = transliterate_english(token)
        if alias and alias not in aliases:
            aliases.append(alias)
    return aliases
