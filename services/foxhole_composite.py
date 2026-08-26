from __future__ import annotations

import hashlib
import json
import logging

from config import config
from services.foxhole_api import FoxholeDataset, FoxholeHQDataProvider
from services.foxhole_api import FoxholeDataError
from services.foxhole_wiki import FoxholeWikiDataProvider
from services.text_normalizer import TextNormalizer

logger = logging.getLogger(__name__)


class CompositeFoxholeDataProvider:
    """FoxholeHQ-first dataset enriched with non-overlapping Wiki facility data."""

    async def fetch_dataset(self) -> FoxholeDataset:
        primary = await FoxholeHQDataProvider().fetch_dataset()
        if not config.FOXHOLE_WIKI_ENABLED:
            return primary
        try:
            secondary = await FoxholeWikiDataProvider().fetch_dataset()
        except Exception as exc:
            logger.warning(
                "Foxhole Wiki enrichment failed; using FoxholeHQ only: %s",
                exc,
                exc_info=not isinstance(exc, FoxholeDataError),
            )
            return FoxholeDataset(
                items=primary.items,
                recipes=primary.recipes,
                categories=primary.categories,
                source_version=primary.source_version,
                source_updated_at=primary.source_updated_at,
                dataset_hash=primary.dataset_hash,
                resource_crate_sizes=primary.resource_crate_sizes,
                supplementary_complete=False,
            )
        items = [dict(row) for row in primary.items]
        recipes = [dict(row) for row in primary.recipes]
        by_name = {
            TextNormalizer.normalize(row["api_name"], remove_service_words=False): row
            for row in items
        }
        id_map: dict[str, str] = {}
        merged_into_primary: set[str] = set()
        for wiki_item in secondary.items:
            name_key = TextNormalizer.normalize(
                wiki_item["api_name"], remove_service_words=False
            )
            existing = by_name.get(name_key)
            if existing is None:
                existing = dict(wiki_item)
                items.append(existing)
                by_name[name_key] = existing
            else:
                merged_into_primary.add(wiki_item["api_id"])
                if not existing.get("image_url"):
                    existing["image_url"] = wiki_item.get("image_url")
                existing_raw = dict(existing.get("raw_data") or {})
                existing_raw["foxholewiki"] = wiki_item.get("raw_data") or {}
                existing["raw_data"] = existing_raw
            id_map[wiki_item["api_id"]] = existing["api_id"]
        existing_methods = {
            (row["api_id"], row["production_method"]) for row in recipes
        }
        existing_buildings = {
            (row["api_id"], str(row.get("building") or "").casefold())
            for row in recipes
        }
        for recipe in secondary.recipes:
            mapped = dict(recipe)
            mapped["api_id"] = id_map[recipe["api_id"]]
            key = (mapped["api_id"], mapped["production_method"])
            building_key = (mapped["api_id"], str(mapped.get("building") or "").casefold())
            if recipe["api_id"] in merged_into_primary and building_key in existing_buildings:
                continue
            if key not in existing_methods:
                recipes.append(mapped)
                existing_methods.add(key)
                existing_buildings.add(building_key)
        canonical = json.dumps(
            {"items": items, "recipes": recipes}, ensure_ascii=False,
            sort_keys=True, separators=(",", ":"),
        )
        logger.info(
            "Composite Foxhole dataset ready: items=%d recipes=%d primary=%s secondary=%s",
            len(items), len(recipes), primary.source_version, secondary.source_version,
        )
        return FoxholeDataset(
            items=sorted(items, key=lambda row: row["api_id"]),
            recipes=sorted(recipes, key=lambda row: (row["api_id"], row["production_method"])),
            categories=sorted({str(row["category"]) for row in items}),
            source_version=f"{primary.source_version} + {secondary.source_version}",
            source_updated_at=max(
                (
                    value for value in (primary.source_updated_at, secondary.source_updated_at)
                    if value is not None
                ),
                default=None,
            ),
            dataset_hash=hashlib.sha256(canonical.encode()).hexdigest(),
            resource_crate_sizes=primary.resource_crate_sizes,
        )
