from __future__ import annotations

import abc
import ast
import datetime
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import aiohttp

from config import config
from services.text_normalizer import TextNormalizer

logger = logging.getLogger(__name__)


class FoxholeDataError(RuntimeError):
    pass


# Kept as an import-compatible name for the existing Discord UI.
FoxholeAPIError = FoxholeDataError


@dataclass(slots=True)
class FoxholeDataset:
    items: list[dict[str, Any]]
    recipes: list[dict[str, Any]]
    categories: list[str]
    source_version: str
    source_updated_at: datetime.datetime | None
    dataset_hash: str


class FoxholeDataProvider(abc.ABC):
    @abc.abstractmethod
    async def fetch_dataset(self) -> FoxholeDataset:
        raise NotImplementedError

    async def fetch_items(self) -> list[dict[str, Any]]:
        return (await self.fetch_dataset()).items

    async def fetch_recipes(self) -> list[dict[str, Any]]:
        return (await self.fetch_dataset()).recipes

    async def fetch_categories(self) -> list[str]:
        return (await self.fetch_dataset()).categories

    async def get_data_version(self) -> str:
        return (await self.fetch_dataset()).source_version


class _ItemButtonParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: dict[str, dict[str, str]] = {}
        self.script_url: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("src", "").endswith("calculator.js"):
            self.script_url = values["src"]
        if tag != "button" or not values.get("data-item"):
            return
        classes = set((values.get("class") or "").casefold().split())
        category = next(
            (
                value
                for value in (
                    "smallarms", "heavyarms", "heavyammo", "utilities", "supplies",
                    "medical", "uniforms", "vehicles", "shippables",
                )
                if value in classes
            ),
            "unknown",
        )
        faction = "neutral"
        if "colonial" in classes and "warden" not in classes:
            faction = "colonial"
        elif "warden" in classes and "colonial" not in classes:
            faction = "warden"
        self.items[values["data-item"]] = {"category": category, "faction": faction}


class FoxholeHQDataProvider(FoxholeDataProvider):
    """Reads the structured iteminfo dataset embedded in FoxholeHQ's calculator bundle.

    FoxholeHQ currently exposes no public catalogue API. Its calculator ships a
    JavaScript object named ``iteminfo``. This parser extracts that data without
    executing upstream JavaScript and fails closed when the bundle contract changes.
    """

    SOURCE = "foxholehq"
    _OBJECT_MARKER = "const iteminfo="
    _OBJECT_END = ";function _0x221e"
    _ARRAY_START = "var _0x5c45f0=["
    _ARRAY_END = "];_0x221e=function"
    _REFERENCE = re.compile(r"_0x362918\((0x[0-9a-f]+)\)")
    _STRING = re.compile(r"'((?:\\.|[^'\\])*)'", re.DOTALL)
    _NAME_REFERENCE = re.compile(
        r"'((?:\\.|[^'\\])*)'\s*:\s*\{\s*'name'\s*:\s*"
        r"_0x362918\((0x[0-9a-f]+)\)"
    )
    _VERSION = re.compile(
        r"Up to date with\s+(Patch\s+[^<(]+?)\s*\(Last Updated\s+([^)]+)\)",
        re.IGNORECASE,
    )
    _PRODUCES = re.compile(r"(\d+)x\s+per\s+crate", re.IGNORECASE)
    _MPF_CATEGORIES = {
        "smallarms", "heavyarms", "heavyammo", "supplies", "uniforms", "vehicles",
        "shippables",
    }
    _VEHICLE_TYPES = {
        "apc", "armored car", "boat", "construction vehicle", "half-track",
        "light tank", "motorcycle", "pushgun", "tank", "tankette", "trailer",
        "truck", "vehicle",
    }

    def __init__(self, base_url: str | None = None, min_items: int | None = None) -> None:
        self.base_url = (
            config.FOXHOLEHQ_BASE_URL if base_url is None else base_url
        ).rstrip("/")
        self.min_items = min_items if min_items is not None else config.FOXHOLEHQ_MIN_ITEMS

    async def fetch_dataset(self) -> FoxholeDataset:
        if not self.base_url:
            raise FoxholeDataError("FOXHOLEHQ_BASE_URL не настроен")
        timeout = aiohttp.ClientTimeout(total=30)
        headers = {"User-Agent": "AFC-Ticket-Bot/2.0 (FoxholeHQ catalogue sync)"}
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                html = await self._get_text(session, f"{self.base_url}/calculator")
                page = _ItemButtonParser()
                page.feed(html)
                script_url = urljoin(
                    f"{self.base_url}/calculator",
                    page.script_url or "/static/calculator.js",
                )
                bundle = await self._get_text(session, script_url)
        except (aiohttp.ClientError, TimeoutError, UnicodeError) as exc:
            raise FoxholeDataError(f"FoxholeHQ недоступен: {exc}") from exc

        version, updated_at = self._parse_version(html)
        raw_items = self._parse_iteminfo(bundle)
        items, recipes = self._normalize(raw_items, page.items, version, updated_at)
        self._validate(items, recipes)
        canonical = json.dumps(
            {"items": items, "recipes": recipes},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return FoxholeDataset(
            items=items,
            recipes=recipes,
            categories=sorted({item["category"] for item in items}),
            source_version=version,
            source_updated_at=updated_at,
            dataset_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        )

    @staticmethod
    async def _get_text(session: aiohttp.ClientSession, url: str) -> str:
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.text()

    @classmethod
    def _decode_string(cls, value: str) -> str:
        try:
            return ast.literal_eval("'" + value + "'")
        except (SyntaxError, ValueError) as exc:
            raise FoxholeDataError("FoxholeHQ bundle содержит неподдерживаемую строку") from exc

    @classmethod
    def _parse_iteminfo(cls, bundle: str) -> dict[str, dict[str, Any]]:
        object_start = bundle.find(cls._OBJECT_MARKER)
        object_end = bundle.find(cls._OBJECT_END, object_start)
        array_start = bundle.find(cls._ARRAY_START, object_end)
        array_end = bundle.find(cls._ARRAY_END, array_start)
        if min(object_start, object_end, array_start, array_end) < 0:
            raise FoxholeDataError("Структура calculator.js изменилась: iteminfo не найден")

        object_source = bundle[object_start + len(cls._OBJECT_MARKER):object_end]
        array_source = bundle[array_start + len(cls._ARRAY_START):array_end]
        strings = [cls._decode_string(match.group(1)) for match in cls._STRING.finditer(array_source)]
        if not strings:
            raise FoxholeDataError("Структура calculator.js изменилась: таблица строк пуста")

        base = 0x194
        scores: list[tuple[int, int]] = []
        name_refs = list(cls._NAME_REFERENCE.finditer(object_source))
        for shift in range(len(strings)):
            score = sum(
                strings[(int(match.group(2), 16) - base + shift) % len(strings)]
                == cls._decode_string(match.group(1))
                for match in name_refs
            )
            scores.append((score, shift))
        score, shift = max(scores)
        if score < 10:
            raise FoxholeDataError("Структура calculator.js изменилась: не удалось декодировать iteminfo")

        def replace_reference(match: re.Match[str]) -> str:
            index = int(match.group(1), 16) - base
            return repr(strings[(index + shift) % len(strings)])

        decoded = cls._REFERENCE.sub(replace_reference, object_source)
        try:
            result = ast.literal_eval(decoded)
        except (SyntaxError, ValueError) as exc:
            raise FoxholeDataError("Структура calculator.js изменилась: iteminfo повреждён") from exc
        if not isinstance(result, dict):
            raise FoxholeDataError("FoxholeHQ iteminfo имеет неверный тип")
        return result

    @classmethod
    def _parse_version(cls, html: str) -> tuple[str, datetime.datetime | None]:
        match = cls._VERSION.search(html)
        if not match:
            return "unknown", None
        version = match.group(1).strip()
        try:
            updated_at = datetime.datetime.strptime(match.group(2).strip(), "%m/%d/%y")
        except ValueError:
            updated_at = None
        return version, updated_at

    @classmethod
    def _normalize(
        cls,
        raw_items: dict[str, dict[str, Any]],
        page_items: dict[str, dict[str, str]],
        version: str,
        updated_at: datetime.datetime | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        items: list[dict[str, Any]] = []
        recipes: list[dict[str, Any]] = []
        for upstream_key, raw in raw_items.items():
            if not isinstance(raw, dict):
                continue
            api_name = str(raw.get("name") or upstream_key).strip()
            metadata = page_items.get(upstream_key) or page_items.get(api_name) or {}
            category = metadata.get("category", "unknown")
            item_type = str(raw.get("type") or "unknown").strip()
            is_vehicle = category == "vehicles" or item_type.casefold() in cls._VEHICLE_TYPES
            match = cls._PRODUCES.search(str(raw.get("produces") or ""))
            crate_size = int(match.group(1)) if match else 1
            cost = {
                resource: int(raw.get(resource) or 0)
                for resource in ("bmat", "rmat", "emat", "hemat")
                if int(raw.get(resource) or 0) > 0
            }
            api_id = "foxholehq:" + TextNormalizer.normalize(upstream_key, remove_service_words=False)
            fingerprint_data = {
                "type": item_type,
                "description": raw.get("desc"),
                "ammo": raw.get("ammo"),
                "produces": raw.get("produces"),
            }
            fingerprint = hashlib.sha256(
                json.dumps(fingerprint_data, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            mpf_available = category in cls._MPF_CATEGORIES
            factory_method = "garage" if is_vehicle else "factory"
            factory_cost = cost
            if is_vehicle and crate_size >= 3 and all(value % 3 == 0 for value in cost.values()):
                factory_cost = {resource: value // 3 for resource, value in cost.items()}
            item = {
                "api_id": api_id[:200],
                "upstream_key": upstream_key,
                "api_name": api_name,
                "category": category,
                "faction": metadata.get("faction"),
                "is_vehicle": is_vehicle,
                "crate_size": crate_size,
                "amount_produced": crate_size,
                "vehicle_crate_size": crate_size if is_vehicle else 1,
                "factory_site": factory_method.title(),
                "factory_cost": factory_cost,
                "mpf_base_cost": cost if mpf_available else {},
                "mpf_available": mpf_available,
                "mpf_max_crates": 5 if is_vehicle else 9,
                "source": cls.SOURCE,
                "source_version": version,
                "source_updated_at": updated_at.isoformat() if updated_at else None,
                "upstream_fingerprint": fingerprint,
                "raw_data": raw,
            }
            items.append(item)
            recipes.append({
                "api_id": item["api_id"],
                "production_method": factory_method,
                "output_quantity": 1,
                "output_unit": "vehicle" if is_vehicle else "crate",
                "materials": factory_cost,
                "raw_data": raw,
            })
            if mpf_available:
                recipes.append({
                    "api_id": item["api_id"],
                    "production_method": "mpf",
                    "output_quantity": crate_size if is_vehicle else 1,
                    "output_unit": "vehicle" if is_vehicle else "crate",
                    "materials": cost,
                    "raw_data": raw,
                })
        items.sort(key=lambda row: row["api_id"])
        recipes.sort(key=lambda row: (row["api_id"], row["production_method"]))
        return items, recipes

    def _validate(self, items: list[dict[str, Any]], recipes: list[dict[str, Any]]) -> None:
        vehicles = sum(item["is_vehicle"] for item in items)
        weapons = sum(
            item["category"] in {"smallarms", "heavyarms", "heavyammo"} for item in items
        )
        broken = [recipe for recipe in recipes if not recipe["materials"]]
        if len(items) < self.min_items or not recipes or not vehicles or not weapons:
            raise FoxholeDataError(
                "FoxholeHQ dataset не прошёл проверку целостности "
                f"(items={len(items)}, recipes={len(recipes)}, vehicles={vehicles}, weapons={weapons})"
            )
        if len(broken) > max(5, len(recipes) // 10):
            raise FoxholeDataError(
                f"FoxholeHQ dataset содержит слишком много пустых рецептов: {len(broken)}"
            )


# Old name retained for extensions that instantiated the former client.
FoxholeAPIClient = FoxholeHQDataProvider
