from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import logging
import re
from typing import Any
from urllib.parse import quote

import aiohttp

from config import config
from services.foxhole_api import FoxholeDataError, FoxholeDataset
from services.text_normalizer import TextNormalizer

logger = logging.getLogger(__name__)


class FoxholeWikiDataProvider:
    """Facility and railway recipes from versioned MediaWiki infobox fields."""

    SOURCE = "foxholewiki"
    INFOBOXES = ("Template:Vehicle Infobox", "Template:Item Infobox")
    _VERSION = re.compile(r"current version[^0-9]*(1[.][0-9]+)", re.IGNORECASE)
    _PRD_SOURCE = re.compile(r"^PRD([0-9]+)_Source$", re.IGNORECASE)
    _MATERIAL_ALIASES = {
        "basic materials": "bmat",
        "refined materials": "rmat",
        "explosive powder": "emat",
        "heavy explosive powder": "hemat",
        "processed construction materials": "processed_construction_materials",
        "construction materials": "construction_materials",
        "assembly materials i": "assembly_materials_i",
        "assembly materials ii": "assembly_materials_ii",
        "assembly materials iii": "assembly_materials_iii",
        "assembly materials iv": "assembly_materials_iv",
        "assembly materials v": "assembly_materials_v",
    }

    def __init__(self, api_url: str | None = None) -> None:
        self.api_url = api_url or config.FOXHOLE_WIKI_API_URL

    async def _request(self, session: aiohttp.ClientSession, **params: str) -> dict:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                async with session.get(self.api_url, params={**params, "format": "json", "formatversion": "2"}) as response:
                    if response.status == 429 or response.status >= 500:
                        raise FoxholeDataError(f"Foxhole Wiki HTTP {response.status}")
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
                    if "error" in payload:
                        raise FoxholeDataError(str(payload["error"].get("info") or payload["error"]))
                    return payload
            except (aiohttp.ClientError, TimeoutError, ValueError, FoxholeDataError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
        raise FoxholeDataError(f"Foxhole Wiki недоступна: {last_error}")

    async def _titles(self, session: aiohttp.ClientSession, template: str) -> list[str]:
        titles: list[str] = []
        continuation: str | None = None
        while True:
            params = {
                "action": "query",
                "list": "embeddedin",
                "eititle": template,
                "einamespace": "0",
                "eilimit": "max",
            }
            if continuation:
                params["eicontinue"] = continuation
            payload = await self._request(session, **params)
            titles.extend(
                row["title"] for row in payload.get("query", {}).get("embeddedin", [])
            )
            continuation = payload.get("continue", {}).get("eicontinue")
            if not continuation:
                return titles

    async def _pages(self, session: aiohttp.ClientSession, titles: list[str]) -> list[dict]:
        pages: list[dict] = []
        for offset in range(0, len(titles), 50):
            payload = await self._request(
                session,
                action="query",
                prop="revisions",
                rvprop="content|timestamp",
                rvslots="main",
                titles="|".join(titles[offset:offset + 50]),
            )
            pages.extend(payload.get("query", {}).get("pages", []))
        return pages

    async def _version(self, session: aiohttp.ClientSession) -> str:
        payload = await self._request(
            session,
            action="query",
            list="search",
            srsearch="Scrap Hauler",
            srlimit="10",
        )
        for row in payload.get("query", {}).get("search", []):
            match = self._VERSION.search(row.get("snippet", ""))
            if match:
                return f"Foxhole {match.group(1)}"
        return "Foxhole Wiki live"

    async def fetch_dataset(self) -> FoxholeDataset:
        timeout = aiohttp.ClientTimeout(total=90)
        headers = {
            "User-Agent": "AFC-Discord-Calculator/1.0 (github.com/myhunter263/AFC-ticket-bot)"
        }
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            title_sets = await asyncio.gather(
                *(self._titles(session, template) for template in self.INFOBOXES)
            )
            titles = sorted(set().union(*map(set, title_sets)))
            pages = await self._pages(session, titles)
            version = await self._version(session)
        items: list[dict[str, Any]] = []
        recipes: list[dict[str, Any]] = []
        updated_at: datetime.datetime | None = None
        for page in pages:
            revision = (page.get("revisions") or [{}])[0]
            timestamp = revision.get("timestamp")
            if timestamp:
                value = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00")).replace(tzinfo=None)
                updated_at = max(updated_at, value) if updated_at else value
            text = revision.get("slots", {}).get("main", {}).get("content", "")
            fields, template_name = self.parse_infobox(text)
            if not fields:
                continue
            item, item_recipes = self.normalize_page(
                page.get("title", ""), fields, template_name, version
            )
            if item and item_recipes:
                items.append(item)
                recipes.extend(item_recipes)
        canonical = json.dumps(
            {"items": items, "recipes": recipes}, sort_keys=True, ensure_ascii=False,
            separators=(",", ":"),
        )
        logger.info(
            "Foxhole Wiki dataset loaded: version=%s items=%d recipes=%d",
            version, len(items), len(recipes),
        )
        return FoxholeDataset(
            items=sorted(items, key=lambda row: row["api_id"]),
            recipes=sorted(recipes, key=lambda row: (row["api_id"], row["production_method"])),
            categories=sorted({str(row["category"]) for row in items}),
            source_version=version,
            source_updated_at=updated_at,
            dataset_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        )

    @staticmethod
    def parse_infobox(text: str) -> tuple[dict[str, str], str]:
        candidates = ("Vehicle Infobox", "Item Infobox")
        for template in candidates:
            start = text.casefold().find("{{" + template.casefold())
            if start < 0:
                continue
            depth = 0
            end = start
            while end < len(text) - 1:
                pair = text[end:end + 2]
                if pair == "{{":
                    depth += 1
                    end += 2
                    continue
                if pair == "}}":
                    depth -= 1
                    end += 2
                    if depth == 0:
                        break
                    continue
                end += 1
            block = text[start:end]
            fields: dict[str, str] = {}
            for line in block.splitlines()[1:]:
                if not line.lstrip().startswith("|") or "=" not in line:
                    continue
                key, value = line.lstrip()[1:].split("=", 1)
                fields[key.strip()] = value.strip()
            return fields, template
        return {}, ""

    @classmethod
    def _number(cls, value: str | None, default: int = 1) -> int | float:
        if not value:
            return default
        cleaned = re.sub(r"[^0-9.-]", "", value)
        try:
            number = float(cleaned)
            return int(number) if number.is_integer() else number
        except (TypeError, ValueError):
            return default

    @classmethod
    def resource_key(cls, name: str) -> str:
        plain = re.sub(r"\[\[|\]\]", "", name).split("|")[-1].strip()
        known = cls._MATERIAL_ALIASES.get(plain.casefold())
        if known:
            return known
        normalized = TextNormalizer.normalize(plain, remove_service_words=False)
        return re.sub(r"[^a-z0-9а-яё]+", "_", normalized).strip("_")

    @classmethod
    def normalize_page(
        cls, title: str, fields: dict[str, str], template: str, version: str
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        name = fields.get("name") or title
        codename = fields.get("codename") or TextNormalizer.compact(name)
        api_id = f"foxholewiki:{TextNormalizer.compact(codename)}"[:200]
        recipe_indexes = sorted({
            int(match.group(1))
            for key in fields
            if (match := cls._PRD_SOURCE.match(key))
        })
        if not recipe_indexes:
            return None, []
        is_vehicle = template == "Vehicle Infobox"
        profile = " ".join((
            fields.get("ItemProfileType", ""), fields.get("EquipmentSlot", ""),
            fields.get("shippable_size", ""), fields.get("type", ""),
        )).casefold()
        is_large = is_vehicle or any(marker in profile for marker in ("large", "vehicle", "locomotive", "car"))
        is_material = fields.get("type", "").casefold() in {"material", "resource"}
        crate_size = int(cls._number(fields.get("crate_amount"), 1))
        image = fields.get("image")
        image_url = (
            f"https://foxhole.wiki.gg/wiki/Special:Redirect/file/{quote(image.replace(' ', '_'))}"
            if image else None
        )
        aliases = [value.strip() for value in fields.get("aliases", "").split(",") if value.strip()]
        item = {
            "api_id": api_id,
            "upstream_key": codename,
            "api_name": name,
            "category": fields.get("category") or fields.get("type") or "facility",
            "faction": fields.get("faction", "Both").casefold(),
            "is_vehicle": is_vehicle,
            "production_group": "equipment" if is_large else "item",
            "crate_size": max(1, crate_size),
            "amount_produced": max(1, crate_size),
            "vehicle_crate_size": 1,
            "factory_site": fields.get(f"PRD{recipe_indexes[0]}_Source"),
            "factory_cost": {},
            "mpf_base_cost": {},
            "mpf_available": False,
            "mpf_max_crates": 5 if is_large else 9,
            "source": cls.SOURCE,
            "source_version": version,
            "source_updated_at": None,
            "upstream_fingerprint": hashlib.sha256(
                json.dumps({"name": name, "codename": codename}, sort_keys=True).encode()
            ).hexdigest(),
            "image_url": image_url,
            "raw_data": {
                "source": cls.SOURCE,
                "wiki_page": title,
                "codename": codename,
                "aliases": aliases,
                "type": fields.get("type"),
                "mobility": fields.get("mobility"),
                "shippable_size": fields.get("shippable_size"),
                "calculation_unit": "item" if is_large else "crate",
            },
        }
        recipes: list[dict[str, Any]] = []
        for index in recipe_indexes:
            prefix = f"PRD{index}_"
            building = fields.get(prefix + "Source")
            materials: dict[str, int | float] = {}
            labels: dict[str, str] = {}
            for key, material_name in fields.items():
                match = re.fullmatch(rf"PRD{index}_InputItem([0-9]+)", key, re.IGNORECASE)
                if not match or not material_name:
                    continue
                amount = cls._number(fields.get(prefix + f"InputItem{match.group(1)}Amount"), 1)
                resource_key = cls.resource_key(material_name)
                materials[resource_key] = materials.get(resource_key, 0) + amount
                labels[resource_key] = re.sub(r"\[\[|\]\]", "", material_name).split("|")[-1]
            # Vehicle upgrades consume a base vehicle, outside InputItemN fields.
            base_vehicle = fields.get(prefix + "InputVehicle")
            if base_vehicle:
                key = cls.resource_key(base_vehicle)
                materials[key] = materials.get(key, 0) + cls._number(fields.get(prefix + "InputVehicleAmount"), 1)
                labels[key] = re.sub(r"\[\[|\]\]", "", base_vehicle).split("|")[-1]
            if not building or not materials:
                continue
            method = f"wiki_prd{index}_{TextNormalizer.compact(building)[:28]}"[:50]
            recipes.append({
                "api_id": api_id,
                "production_method": method,
                "output_quantity": int(cls._number(fields.get(prefix + "OutputAmount"), 1)),
                "output_unit": "item" if is_large or is_material else "crate",
                "materials": materials,
                "building": building,
                "recipe_kind": "facility",
                "source": cls.SOURCE,
                "source_version": version,
                "raw_data": {
                    "source": cls.SOURCE,
                    "source_version": version,
                    "wiki_page": title,
                    "production_category": fields.get(prefix + "ProductionCategory"),
                    "input_power": cls._number(fields.get(prefix + "InputPower"), 0),
                    "production_time": cls._number(fields.get(prefix + "ProductionTime"), 0),
                    "material_labels": labels,
                },
            })
        return item, recipes
