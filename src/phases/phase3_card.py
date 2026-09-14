from __future__ import annotations
import asyncio
from typing import Any

import structlog

from ..components.fetcher import Fetcher, FetcherError
from ..components.parser import parse_model_card
from ..components.checkpoint import CheckpointManager
from ..components.storage import Storage
from ..metrics import MODELS_FETCHED_TOTAL

logger = structlog.get_logger(__name__)


class Phase3ModelCardFetcher:
    """Fetches README cards per model."""

    def __init__(self, fetcher: Fetcher, storage: Storage, checkpoint: CheckpointManager, max_concurrent: int = 5, max_items: int | None = None):
        self._fetcher = fetcher
        self._storage = storage
        self._checkpoint = checkpoint
        self._max_concurrent = max_concurrent
        self._max_items = max_items

    async def run(self, pending_ids: list[str], signal_handler: Any) -> tuple[int, int]:
        """Run phase 3. Returns (completed, failed)."""
        if self._max_items:
            pending_ids = pending_ids[:self._max_items]

        last_model_id = self._checkpoint.last_model_id
        if last_model_id:
            try:
                resume_idx = pending_ids.index(last_model_id)
                pending_ids = pending_ids[resume_idx + 1:]
                logger.info("phase3_resuming", last_model_id=last_model_id, remaining=len(pending_ids))
            except ValueError:
                logger.warning("phase3_resume_id_not_found", last_model_id=last_model_id)

        logger.info("phase3_starting", total_pending=len(pending_ids))
        completed = 0
        failed = 0
        semaphore = asyncio.Semaphore(self._max_concurrent)

        async def fetch_one(model_id: str) -> None:
            nonlocal completed, failed
            async with semaphore:
                if signal_handler.should_shutdown:
                    return
                try:
                    text, headers = await self._fetcher.get_text(f"/{model_id}/raw/main/README.md", phase="card")
                    etag = headers.get("etag", "")
                    record = parse_model_card(model_id, text, etag)
                    if record:
                        self._storage.upsert_model_card([record])
                        MODELS_FETCHED_TOTAL.labels(phase="card", status="success").inc()
                        completed += 1
                    else:
                        MODELS_FETCHED_TOTAL.labels(phase="card", status="empty").inc()
                        failed += 1
                except FetcherError as e:
                    if e.status == 404:
                        MODELS_FETCHED_TOTAL.labels(phase="card", status="not_found").inc()
                    elif e.status == 403:
                        MODELS_FETCHED_TOTAL.labels(phase="card", status="gated").inc()
                    else:
                        MODELS_FETCHED_TOTAL.labels(phase="card", status="error").inc()
                        logger.error("phase3_fetch_error", model_id=model_id, error=str(e))
                    failed += 1

        batch_size = 50
        for i in range(0, len(pending_ids), batch_size):
            if signal_handler.should_shutdown:
                break
            batch = pending_ids[i:i + batch_size]
            tasks = [fetch_one(mid) for mid in batch]
            await asyncio.gather(*tasks)
            if batch:
                self._checkpoint.last_model_id = batch[-1]
                self._checkpoint.count = completed
                self._checkpoint.save(force=True)

        self._checkpoint.save(force=True)
        return completed, failed
