from __future__ import annotations
import time
from typing import Any

import structlog

from ..components.fetcher import Fetcher, FetcherError
from ..components.parser import parse_model_list
from ..components.checkpoint import CheckpointManager
from ..components.storage import Storage
from ..metrics import MODELS_FETCHED_TOTAL

logger = structlog.get_logger(__name__)


class Phase1ListModelFetcher:
    """Fetches model list via cursor pagination."""

    def __init__(self, fetcher: Fetcher, storage: Storage, checkpoint: CheckpointManager, max_items: int | None = None):
        self._fetcher = fetcher
        self._storage = storage
        self._checkpoint = checkpoint
        self._max_items = max_items

    async def run(self, get_params: callable, signal_handler: Any) -> tuple[int, int]:
        """Run phase 1. Returns (total_fetched, pages)."""
        cursor = self._checkpoint.cursor
        page = self._checkpoint.page
        total_fetched = self._checkpoint.count

        logger.info("phase1_starting", cursor=cursor, page=page, total_fetched=total_fetched)

        while not signal_handler.should_shutdown:
            if self._max_items and total_fetched >= self._max_items:
                logger.info("phase1_max_items_reached", total=total_fetched)
                break

            params = get_params(cursor)
            try:
                raw, headers = await self._fetcher.get_json("/api/models", params, phase="list")
                if not raw:
                    break

                records = parse_model_list(raw, page, cursor)
                if not records:
                    break

                if self._max_items and total_fetched + len(records) > self._max_items:
                    records = records[:self._max_items - total_fetched]

                written = self._storage.upsert_model_list(records)
                total_fetched += written

                link_header = headers.get("link") or headers.get("Link")
                next_url = self._parse_link_header(link_header)
                if not next_url:
                    break

                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(next_url)
                next_params = parse_qs(parsed.query)
                cursor = next_params.get("cursor", [None])[0]
                if not cursor:
                    break

                page += 1
                self._checkpoint.cursor = cursor
                self._checkpoint.page = page
                self._checkpoint.count = total_fetched
                self._checkpoint.save()

            except FetcherError as e:
                logger.error("phase1_fetcher_error", error=str(e), page=page)
                raise

        self._checkpoint.save(force=True)
        return total_fetched, page

    def _parse_link_header(self, link_header: str | None) -> str | None:
        if not link_header:
            return None
        for part in link_header.split(","):
            if 'rel="next"' in part:
                return part.split(";")[0].strip().strip("<>")
        return None
