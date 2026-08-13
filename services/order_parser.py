from __future__ import annotations

import re

from services.foxhole_types import ParsedOrderLine
from services.text_normalizer import TextNormalizer


class OrderParser:
    _UNIT = re.compile(
        r"^(?P<unit>ящик(?:ов|а|и)?|ящ(?:\.|иков|ика)?|шт(?:\.|ук[аи]?)?|штук)\s+",
        re.IGNORECASE,
    )
    _START = re.compile(r"^\s*(?P<quantity>\d{1,6})\s+(?P<body>.+?)\s*$", re.DOTALL)
    _END = re.compile(r"^\s*(?P<body>.+?)\s+(?P<quantity>\d{1,6})\s*$", re.DOTALL)
    _SAME = re.compile(r"^\s*столько\s+же\s+(?P<body>.+?)\s*$", re.IGNORECASE | re.DOTALL)

    def parse(self, text: str) -> list[ParsedOrderLine]:
        text = re.sub(r"\s+(?:и\s+)?(?:еще|ещё)\s+(?=\d)", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+(?:а\s+)?(?:также|плюс)\s+(?=\d)", "\n", text, flags=re.IGNORECASE)
        # Split free-form prose before every explicit quantity while preserving
        # decimal calibers such as 7.62.
        text = re.sub(r"(?<![\d.])\s+(?=\d{1,6}\s+[а-яёa-z])", "\n", text, flags=re.IGNORECASE)
        chunks = re.split(r"[\n;,]+", text)
        parsed: list[ParsedOrderLine] = []
        for raw_chunk in chunks:
            chunk = raw_chunk.strip()
            if not chunk:
                continue
            match = self._START.match(chunk)
            same_match = self._SAME.match(chunk) if not match else None
            end_match = self._END.match(chunk) if not match and not same_match else None
            if match:
                quantity = int(match.group("quantity"))
                body = match.group("body").strip()
            elif same_match and parsed:
                quantity = parsed[-1].quantity
                body = same_match.group("body").strip()
            elif end_match:
                quantity = int(end_match.group("quantity"))
                body = end_match.group("body").strip()
            else:
                continue
            if quantity <= 0:
                continue
            unit_match = self._UNIT.match(body)
            requested_unit = None
            if unit_match:
                raw_unit = unit_match.group("unit").casefold()
                requested_unit = "crate" if raw_unit.startswith("ящ") else "item"
                body = body[unit_match.end():]
            query = TextNormalizer.normalize(body)
            if query:
                parsed.append(ParsedOrderLine(quantity, requested_unit, query))
        return parsed
