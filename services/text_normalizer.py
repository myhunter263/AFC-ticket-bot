from __future__ import annotations

import re
import unicodedata


class TextNormalizer:
    _DASHES = re.compile(r"[‐‑‒–—−]+")
    _SPACES = re.compile(r"\s+")
    _PUNCTUATION = re.compile(r"[^0-9a-zа-яё.\s-]", re.IGNORECASE)
    _DECIMAL_CALIBER = re.compile(
        r"(?<!\d)(7\s*[.,]?\s*62|12\s*[.,]?\s*7|14\s*[.,]?\s*5|"
        r"94\s*[.,]?\s*5)\s*(?:мм|mm)?(?!\d)",
        re.IGNORECASE,
    )
    _WHOLE_CALIBER = re.compile(
        r"(?<!\d)(9|20|30|40|68|75|120|150|300)\s*(?:мм|mm)(?!\d)",
        re.IGNORECASE,
    )
    _SERVICE_WORDS = {
        "нужно", "надо", "закажите", "заказать", "пожалуйста", "мне", "нам",
        "ещё", "еще", "также", "дайте", "хочу", "возьмите",
    }

    @classmethod
    def normalize(cls, value: str, *, remove_service_words: bool = True) -> str:
        value = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
        value = cls._DASHES.sub(" ", value).replace("-", " ")

        def normalize_decimal_caliber(match: re.Match[str]) -> str:
            compact = re.sub(r"[\s.,]", "", match.group(1))
            return {
                "762": "7.62",
                "127": "12.7",
                "145": "14.5",
                "945": "94.5",
            }[compact]

        value = cls._DECIMAL_CALIBER.sub(normalize_decimal_caliber, value)
        value = cls._WHOLE_CALIBER.sub(lambda match: match.group(1), value)
        value = cls._PUNCTUATION.sub(" ", value)
        value = cls._SPACES.sub(" ", value).strip(" .-")
        if remove_service_words:
            words = [word for word in value.split() if word not in cls._SERVICE_WORDS]
            value = " ".join(words)
        return value

    @classmethod
    def compact(cls, value: str) -> str:
        return cls.normalize(value).replace(" ", "").replace(".", "")
