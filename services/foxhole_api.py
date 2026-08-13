from __future__ import annotations

import logging
from typing import Any

import aiohttp

from config import config

logger = logging.getLogger(__name__)


class FoxholeAPIError(RuntimeError):
    pass


class FoxholeAPIClient:
    def __init__(self, url: str | None = None) -> None:
        self.url = (url if url is not None else config.FOXHOLE_ITEM_API_URL).strip()

    async def fetch_items(self) -> list[dict[str, Any]]:
        if not self.url:
            raise FoxholeAPIError("FOXHOLE_ITEM_API_URL не настроен")
        timeout = aiohttp.ClientTimeout(total=30)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    self.url,
                    headers={"User-Agent": "AFC-Ticket-Bot/1.0"},
                ) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            logger.error("Foxhole Item API request failed: %s", exc)
            raise FoxholeAPIError(str(exc)) from exc

        if isinstance(payload, dict):
            payload = payload.get("items") or payload.get("data") or []
        if not isinstance(payload, list):
            raise FoxholeAPIError("API вернул неподдерживаемый формат каталога")
        return [item for item in payload if isinstance(item, dict)]
