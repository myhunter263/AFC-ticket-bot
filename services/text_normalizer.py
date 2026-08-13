from __future__ import annotations

import re
import unicodedata


class TextNormalizer:
    _DASHES = re.compile(r"[‐‑‒–—−]+")
    _SPACES = re.compile(r"\s+")
    _PUNCTUATION = re.compile(r"[^0-9a-zа-яё.\s-]", re.IGNORECASE)
    _CALIBER = re.compile(r"(?<!\d)(7)\s*[.]?\s*(62)(?:\s*мм)?(?!\d)", re.IGNORECASE)
    _SERVICE_WORDS = {
        "нужно", "надо", "закажите", "заказать", "пожалуйста", "мне", "нам",
        "ещё", "еще", "также", "дайте", "хочу", "возьмите",
    }

    @classmethod
    def normalize(cls, value: str, *, remove_service_words: bool = True) -> str:
        value = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
        value = cls._DASHES.sub("-", value)
        value = cls._CALIBER.sub("7.62", value)
        value = cls._PUNCTUATION.sub(" ", value)
        value = cls._SPACES.sub(" ", value).strip(" .-")
        if remove_service_words:
            words = [word for word in value.split() if word not in cls._SERVICE_WORDS]
            value = " ".join(words)
        return value

    @classmethod
    def compact(cls, value: str) -> str:
        return cls.normalize(value).replace(" ", "").replace(".", "")
