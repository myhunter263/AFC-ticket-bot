from __future__ import annotations

import abc
import datetime
import hashlib
import html
import json
import logging
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

import aiohttp

from config import config

logger = logging.getLogger(__name__)


class FoxholeDataError(RuntimeError):
    pass


FoxholeAPIError = FoxholeDataError


@dataclass(slots=True)
class FoxholeDataset:
    items: list[dict[str, Any]]
    recipes: list[dict[str, Any]]
    categories: list[str]
    source_version: str
    source_updated_at: datetime.datetime | None
    dataset_hash: str
    resource_crate_sizes: dict[str, int] | None = None


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


class _FactoryPageParser(HTMLParser):
    """Extracts server-rendered item records from Foxhole Queues Calculator."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        classes = set(values.get("class", "").split())
        if tag == "div" and "item" in classes and values.get("id"):
            self.items.append(values)


class FoxholeHQDataProvider(FoxholeDataProvider):
    """Provider for the Update 65 Foxhole Queues Calculator on foxholehq.net.

    The site server-renders each item as a structured ``div.item`` with stable ID,
    production queue and material attributes. Tooltip markup supplies its name,
    type, description, crate quantity and explicit production methods.
    """

    SOURCE = "foxholehq"
    FACTORY_PATH = "/factory"
    _VERSION = re.compile(r"Updated\s+to\s+1[.]([0-9]+)(?:[.]x)+", re.IGNORECASE)
    _RELEASE = re.compile(
        r"([0-9]+[a-z]{2}\s+[A-Za-z]+\s+[0-9]{4}).{0,1200}?Update FQC to Update\s+([0-9]+)",
        re.IGNORECASE | re.DOTALL,
    )
    _TITLE = re.compile(r"item-title-box.*?<span>(.*?)</span>", re.IGNORECASE | re.DOTALL)
    _TYPE = re.compile(r"item-type[^>]*>(.*?)<", re.IGNORECASE | re.DOTALL)
    _DESCRIPTION = re.compile(r"item-description[^>]*>(.*?)<", re.IGNORECASE | re.DOTALL)
    _CRATE = re.compile(r"item-crates[^>]*>.*?crate of\s+(\d+)x", re.IGNORECASE | re.DOTALL)
    _PRODUCED_AT = re.compile(r"Produced at:\s*([^<]+)", re.IGNORECASE)
    _MPF_ONLY_CATEGORIES = {"vehicles", "structures"}
    _MATERIALS = {
        "bmats": "bmat",
        "rmats": "rmat",
        "epowders": "emat",
        "hepowders": "hemat",
    }
    _SCRIPT = re.compile(r'src=["\']([^"\']*assets/js/scripts[^"\']+[.]js)["\']', re.IGNORECASE)
    _RESOURCE_CRATES = re.compile(
        r"\{\s*bmats\s*:\s*(\d+)\s*,\s*rmats\s*:\s*(\d+)\s*,\s*"
        r"epowders\s*:\s*(\d+)\s*,\s*hepowders\s*:\s*(\d+)\s*\}"
    )

    def __init__(self, base_url: str | None = None, min_items: int | None = None) -> None:
        self.base_url = (
            config.FOXHOLEHQ_BASE_URL if base_url is None else base_url
        ).rstrip("/")
        self.min_items = min_items if min_items is not None else config.FOXHOLEHQ_MIN_ITEMS

    async def fetch_dataset(self) -> FoxholeDataset:
        if not self.base_url:
            raise FoxholeDataError("FOXHOLEHQ_BASE_URL не настроен")
        timeout = aiohttp.ClientTimeout(total=30)
        headers = {"User-Agent": "AFC-Ticket-Bot/2.1 (FoxholeHQ catalogue sync)"}
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(f"{self.base_url}{self.FACTORY_PATH}") as response:
                    response.raise_for_status()
                    page = await response.text()
                script_match = self._SCRIPT.search(page)
                if not script_match:
                    raise FoxholeDataError("FoxholeHQ не указал скрипт с размерами ящиков ресурсов")
                script_url = script_match.group(1)
                if not script_url.startswith("http"):
                    script_url = f"{self.base_url}/{script_url.lstrip('/')}"
                async with session.get(script_url) as response:
                    response.raise_for_status()
                    script = await response.text()
        except (aiohttp.ClientError, TimeoutError, UnicodeError) as exc:
            raise FoxholeDataError(f"FoxholeHQ недоступен: {exc}") from exc
        return self.parse_page(page, script)

    def parse_page(self, page: str, script: str = "") -> FoxholeDataset:
        parser = _FactoryPageParser()
        parser.feed(page)
        version, updated_at = self._parse_version(page)
        resource_crate_sizes = self._parse_resource_crates(script)
        items, recipes = self._normalize(parser.items, version, updated_at)
        self._validate(items, recipes)
        canonical = json.dumps(
            {"items": items, "recipes": recipes, "resource_crate_sizes": resource_crate_sizes},
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
            resource_crate_sizes=resource_crate_sizes,
        )

    @classmethod
    def _parse_resource_crates(cls, script: str) -> dict[str, int]:
        match = cls._RESOURCE_CRATES.search(script)
        if not match:
            raise FoxholeDataError("FoxholeHQ не предоставил размеры ящиков ресурсов")
        return dict(zip(("bmat", "rmat", "emat", "hemat"), map(int, match.groups())))

    @classmethod
    def _parse_version(cls, page: str) -> tuple[str, datetime.datetime | None]:
        version_match = cls._VERSION.search(page)
        if not version_match:
            raise FoxholeDataError("FoxholeHQ не указал версию игрового dataset")
        patch = version_match.group(1)
        updated_at = None
        release_matches = list(cls._RELEASE.finditer(page))
        release = next((match for match in release_matches if match.group(2) == patch), None)
        if release:
            for date_format in ("%dth %B %Y", "%dst %B %Y", "%dnd %B %Y", "%drd %B %Y"):
                try:
                    updated_at = datetime.datetime.strptime(release.group(1), date_format)
                    break
                except ValueError:
                    continue
        return f"Patch {patch}", updated_at

    @classmethod
    def _text(cls, pattern: re.Pattern[str], tooltip: str, default: str = "") -> str:
        match = pattern.search(tooltip)
        if not match:
            return default
        value = re.sub(r"<[^>]+>", "", match.group(1))
        return html.unescape(value).strip()

    @classmethod
    def _normalize(
        cls,
        rows: list[dict[str, str]],
        version: str,
        updated_at: datetime.datetime | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        items: list[dict[str, Any]] = []
        recipes: list[dict[str, Any]] = []
        for row in rows:
            external_id = row["id"].strip().casefold()
            tooltip = html.unescape(row.get("title", ""))
            api_name = cls._text(cls._TITLE, tooltip)
            if not api_name:
                continue
            category = row.get("queue") or "unknown"
            classes = set(row.get("class", "").casefold().split())
            faction = "colonial" if "colonial" in classes else "warden" if "warden" in classes else "neutral"
            item_type = cls._text(cls._TYPE, tooltip, "unknown")
            description = cls._text(cls._DESCRIPTION, tooltip)
            crate_match = cls._CRATE.search(tooltip)
            crate_size = int(crate_match.group(1)) if crate_match else 1
            produced_at = cls._text(cls._PRODUCED_AT, tooltip)
            methods = [value.strip() for value in produced_at.split(",") if value.strip()]
            is_vehicle = category == "vehicles"
            production_group = (
                "equipment" if category in cls._MPF_ONLY_CATEGORIES else "item"
            )
            mpf_available = category in cls._MPF_ONLY_CATEGORIES or any(
                "mass production factory" in method.casefold() for method in methods
            )
            cost = {
                target: int(row[source])
                for source, target in cls._MATERIALS.items()
                if row.get(source) and int(row[source]) > 0
            }
            factory_cost = cost
            if is_vehicle and crate_size > 1 and all(value % crate_size == 0 for value in cost.values()):
                factory_cost = {resource: value // crate_size for resource, value in cost.items()}
            standard_method = next(
                (method for method in methods if "mass production" not in method.casefold()),
                "Garage" if is_vehicle else "Factory",
            )
            fingerprint_payload = {
                "type": item_type,
                "description": description,
                "crate_size": crate_size,
                "methods": methods,
            }
            fingerprint = hashlib.sha256(
                json.dumps(fingerprint_payload, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            raw_data = {
                "external_id": external_id,
                "type": item_type,
                "description": description,
                "production_methods": methods,
                "time": float(row.get("time") or 0),
                "attributes": {key: row[key] for key in cls._MATERIALS if row.get(key)},
            }
            item = {
                "api_id": f"foxholehq:{external_id}"[:200],
                "upstream_key": external_id,
                "api_name": api_name,
                "category": category,
                "faction": faction,
                "is_vehicle": is_vehicle,
                "production_group": production_group,
                "crate_size": crate_size,
                "amount_produced": crate_size,
                "vehicle_crate_size": crate_size if is_vehicle else 1,
                "factory_site": standard_method,
                "factory_cost": factory_cost,
                "mpf_base_cost": cost if mpf_available else {},
                "mpf_available": mpf_available,
                "mpf_max_crates": 5 if production_group == "equipment" else 9,
                "source": cls.SOURCE,
                "source_version": version,
                "source_updated_at": updated_at.isoformat() if updated_at else None,
                "upstream_fingerprint": fingerprint,
                "raw_data": raw_data,
            }
            items.append(item)
            recipes.append({
                "api_id": item["api_id"],
                "production_method": standard_method.casefold().replace(" ", "_"),
                "output_quantity": 1,
                "output_unit": (
                    "vehicle" if is_vehicle
                    else "equipment" if production_group == "equipment"
                    else "crate"
                ),
                "materials": factory_cost,
                "raw_data": {
                    **raw_data,
                    "source": cls.SOURCE,
                    "source_version": version,
                    "upstream_materials": cost,
                    "normalization": (
                        "vehicle_crate_cost_divided_by_crate_size"
                        if is_vehicle and crate_size > 1 else "unchanged"
                    ),
                },
            })
            if mpf_available:
                recipes.append({
                    "api_id": item["api_id"],
                    "production_method": "mpf",
                    "output_quantity": 1,
                    "output_unit": (
                        "vehicle_crate" if is_vehicle
                        else "equipment_crate" if production_group == "equipment"
                        else "crate"
                    ),
                    "materials": cost,
                    "raw_data": {
                        **raw_data,
                        "source": cls.SOURCE,
                        "source_version": version,
                        "upstream_materials": cost,
                        "vehicles_per_crate": crate_size if is_vehicle else None,
                        "crates_per_mpf_queue": 5 if is_vehicle else 9,
                        "normalization": "unchanged",
                    },
                })
        items.sort(key=lambda value: value["api_id"])
        recipes.sort(key=lambda value: (value["api_id"], value["production_method"]))
        return items, recipes

    def _validate(self, items: list[dict[str, Any]], recipes: list[dict[str, Any]]) -> None:
        vehicles = sum(item["is_vehicle"] for item in items)
        weapons = sum(
            item["category"] in {"small-arms", "heavy-arms", "heavy-ammunition"}
            for item in items
        )
        invalid = [item for item in items if not item["api_name"] or not item["factory_cost"]]
        if len(items) < self.min_items or not recipes or not vehicles or not weapons:
            raise FoxholeDataError(
                "FoxholeHQ dataset не прошёл проверку целостности "
                f"(items={len(items)}, recipes={len(recipes)}, vehicles={vehicles}, weapons={weapons})"
            )
        if invalid:
            raise FoxholeDataError(
                f"FoxholeHQ dataset содержит повреждённые позиции: {len(invalid)}"
            )


FoxholeAPIClient = FoxholeHQDataProvider
