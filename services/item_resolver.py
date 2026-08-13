from __future__ import annotations

import logging

from rapidfuzz import fuzz

from config import config
from services.foxhole_types import CatalogItem, ResolvedItem, ResolvedItemCandidates
from services.text_normalizer import TextNormalizer

logger = logging.getLogger(__name__)


class ItemResolver:
    def __init__(
        self,
        items: list[CatalogItem],
        auto_threshold: int | None = None,
        confirm_threshold: int | None = None,
    ) -> None:
        self.items = items
        self.auto_threshold = auto_threshold or config.FOXHOLE_RESOLVE_AUTO_THRESHOLD
        self.confirm_threshold = confirm_threshold or config.FOXHOLE_RESOLVE_CONFIRM_THRESHOLD

    def resolve(self, query: str) -> ResolvedItem | ResolvedItemCandidates:
        normalized = TextNormalizer.normalize(query)
        compact = TextNormalizer.compact(query)

        # The order is intentional: community vocabulary wins over upstream names.
        exact_groups = (
            ("alias", lambda item: item.aliases),
            ("ru_name", lambda item: [item.ru_name]),
            ("api_name", lambda item: [item.api_name]),
        )
        for matched_by, getter in exact_groups:
            for item in self.items:
                for text in getter(item):
                    candidate = TextNormalizer.normalize(text)
                    if normalized == candidate or compact == TextNormalizer.compact(text):
                        source = "exact_alias" if matched_by == "alias" else matched_by
                        return ResolvedItem(item, 100, source, text, False)

        scored: dict[str, ResolvedItem] = {}
        fuzzy_groups = (
            ("fuzzy_alias", lambda item: item.aliases, 3),
            ("fuzzy_ru_name", lambda item: [item.ru_name], 1),
            ("fuzzy_api_name", lambda item: [item.api_name], -4),
        )
        for matched_by, getter, bonus in fuzzy_groups:
            for item in self.items:
                for text in getter(item):
                    candidate = TextNormalizer.normalize(text)
                    priority_bonus = 0
                    if matched_by == "fuzzy_alias":
                        metadata = item.alias_metadata.get(candidate, {})
                        priority_bonus = max(-8, min(8, (int(metadata.get("priority", 100)) - 100) // 10))
                    score = min(100, round(fuzz.WRatio(normalized, candidate) + bonus + priority_bonus))
                    current = scored.get(item.api_id)
                    if current is None or score > current.confidence:
                        scored[item.api_id] = ResolvedItem(
                            item=item,
                            confidence=score,
                            matched_by=matched_by,
                            matched_text=text,
                            requires_confirmation=score < self.auto_threshold,
                        )

        candidates = sorted(scored.values(), key=lambda result: result.confidence, reverse=True)
        if candidates and candidates[0].confidence >= self.confirm_threshold:
            if candidates[0].requires_confirmation:
                logger.warning(
                    "Low-confidence Foxhole item query %r: %s (%d%%)",
                    query,
                    candidates[0].item.api_name,
                    candidates[0].confidence,
                )
            return candidates[0]

        logger.warning("Unknown Foxhole item query: %r", query)
        return ResolvedItemCandidates(query=query, candidates=candidates[:5])

    def debug(self, query: str) -> dict:
        normalized = TextNormalizer.normalize(query)
        result = self.resolve(query)
        candidates = result.candidates if isinstance(result, ResolvedItemCandidates) else [result]
        return {
            "input": query,
            "normalized": normalized,
            "matched": None if isinstance(result, ResolvedItemCandidates) else result,
            "source": (
                "database_alias"
                if not isinstance(result, ResolvedItemCandidates)
                and result.matched_by == "exact_alias"
                else result.matched_by
                if not isinstance(result, ResolvedItemCandidates)
                else "candidates"
            ),
            "candidates": candidates[:5],
        }
