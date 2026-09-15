from __future__ import annotations
import asyncio
import time
from collections.abc import Callable
from enum import IntEnum
from typing import Any

import structlog

from src.config import Config
from src.metrics import (
    MODELS_FETCHED_TOTAL,
    PHASE_PROGRESS_PCT,
    LIST_COUNT,
    INFO_COUNT,
    CARD_COUNT,
    PHASE_STATUS,
    ACTIVE_WORKERS,
    THROUGHPUT_MODELS_PER_SECOND,
    DB_SIZE_BYTES,
    DISK_FREE_BYTES,
    RATE_LIMIT_REMAINING,
    RATE_LIMIT_HITS_TOTAL,
    REQUESTS_TOTAL,
    REQUEST_DURATION_SECONDS,
    BATCH_COMMIT_DURATION_SECONDS,
    MEDIAN_REQUESTS_PER_MINUTE,
    STDDEV_REQUESTS_PER_MINUTE,
    MEDIAN_RATE_LIMIT_EFFICIENCY,
    STDDEV_RATE_LIMIT_EFFICIENCY,
    PHASE_RUNTIME_SECONDS,
    PHASE_ETA_SECONDS,
)
from src.monitoring import MetricsPusher, LogShipper, RateLimitMonitor
from src.aggregator import AggregationEngine
from src.query_server import QueryServer
from src.components.fetcher import Fetcher
from src.components.storage import Storage
from src.components.checkpoint import CheckpointManager
from src.phases.phase1_list import Phase1ListModelFetcher
from src.phases.phase2_info import Phase2ModelInfoFetcher
from src.phases.phase3_card import Phase3ModelCardFetcher

logger = structlog.get_logger(__name__)


def _parse_link_header(link_header: str | None) -> str | None:
    """Parse Link header to extract next cursor URL."""
    if not link_header:
        return None
    for part in link_header.split(","):
        if 'rel="next"' in part:
            return part.split(";")[0].strip().strip("<>")
    return None


class PhaseState(IntEnum):
    PENDING = 0
    RUNNING = 1
    COMPLETE = 2
    FAILED = 3


class PhaseGovernor:
    """Manages phase transitions based on thresholds."""

    def __init__(self, config: Config, storage: 'Storage'):
        self._config = config
        self._storage = storage
        self._phase_states: dict[str, PhaseState] = {
            "list": PhaseState.PENDING,
            "info": PhaseState.PENDING,
            "card": PhaseState.PENDING,
        }
        self._phase_progress: dict[str, float] = {
            "list": 0.0,
            "info": 0.0,
            "card": 0.0,
        }

    def get_state(self, phase: str) -> PhaseState:
        return self._phase_states.get(phase, PhaseState.PENDING)

    def set_state(self, phase: str, state: PhaseState) -> None:
        self._phase_states[phase] = state
        PHASE_STATUS.labels(phase=phase).set(int(state))
        logger.info("phase_state_change", phase=phase, state=state.name)

    def set_progress(self, phase: str, pct: float) -> None:
        self._phase_progress[phase] = pct
        PHASE_PROGRESS_PCT.labels(phase=phase).set(pct)

    def get_progress(self, phase: str) -> float:
        return self._phase_progress.get(phase, 0.0)

    def can_start_info(self) -> bool:
        if self._phase_states["info"] != PhaseState.PENDING:
            return False
        list_pct = self._phase_progress.get("list", 0.0)
        return list_pct >= self._config.phase_gating.phase2_start_threshold_pct

    def can_start_card(self) -> bool:
        if self._phase_states["card"] != PhaseState.PENDING:
            return False
        return self._phase_states["info"] == PhaseState.COMPLETE

    def is_complete(self) -> bool:
        return all(s == PhaseState.COMPLETE for s in self._phase_states.values())


class SignalHandler:
    """Handles SIGINT/SIGTERM for graceful shutdown."""

    def __init__(self):
        self._shutdown = False
        self._callbacks: list[callable] = []

    @property
    def should_shutdown(self) -> bool:
        return self._shutdown

    def on_shutdown(self, callback: callable) -> None:
        self._callbacks.append(callback)

    def install(self) -> None:
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._handle_signal, sig)
            except NotImplementedError:
                signal.signal(sig, self._handle_signal_sync)

    def _handle_signal(self, sig: signal.Signals) -> None:
        logger.info("signal_received", signal=sig.name)
        self._shutdown = True
        for cb in self._callbacks:
            try:
                cb()
            except Exception:
                pass

    def _handle_signal_sync(self, signum: int, frame: Any) -> None:
        logger.info("signal_received_sync", signal=signum)
        self._shutdown = True
        for cb in self._callbacks:
            try:
                cb()
            except Exception:
                pass


class HealthChecker:
    """Checks system health: DB, API, disk space."""

    def __init__(self, config: Config, storage: 'Storage'):
        self._config = config
        self._storage = storage

    def check_db(self) -> bool:
        try:
            count = self._storage.get_list_count()
            return True
        except Exception:
            return False

    def check_disk(self) -> tuple[bool, float]:
        import shutil
        try:
            stat = shutil.disk_usage(self._config.storage.duckdb_path)
            free_gb = stat.free / (1024 ** 3)
            return free_gb > 10.0, free_gb
        except OSError:
            return False, 0.0

    def check_api(self) -> bool:
        import httpx
        try:
            resp = httpx.get(
                f"{self._config.huggingface.base_url}/api/models",
                params={"limit": 1},
                timeout=10.0,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def is_healthy(self) -> tuple[bool, list[str]]:
        issues = []
        if not self.check_db():
            issues.append("database_unhealthy")
        ok, free_gb = self.check_disk()
        if not ok:
            issues.append(f"low_disk_space: {free_gb:.1f}GB free")
        if not self.check_api():
            issues.append("api_unhealthy")
        return len(issues) == 0, issues


class ProgressTracker:
    """Tracks crawl progress and computes ETA."""

    def __init__(self, phase: str, total: int | None = None):
        self._phase = phase
        self._total = total
        self._completed = 0
        self._failed = 0
        self._active_workers = 0
        self._start_time = time.monotonic()
        self._last_log_time = 0.0

    @property
    def completed(self) -> int:
        return self._completed

    @property
    def failed(self) -> int:
        return self._failed

    def increment(self, count: int = 1, failed: int = 0) -> None:
        self._completed += count
        self._failed += failed

    def get_progress_pct(self) -> float:
        if self._total and self._total > 0:
            return (self._completed / self._total) * 100
        return 0.0

    def get_throughput(self) -> float:
        elapsed = time.monotonic() - self._start_time
        if elapsed > 0:
            return self._completed / elapsed
        return 0.0

    def get_eta_seconds(self) -> float | None:
        if not self._total or self._total == 0:
            return None
        remaining = self._total - self._completed
        throughput = self.get_throughput()
        if throughput > 0:
            return remaining / throughput
        return None

    def should_log_progress(self, interval_seconds: float = 10.0) -> bool:
        now = time.monotonic()
        if now - self._last_log_time >= interval_seconds:
            self._last_log_time = now
            return True
        return False

    def log_progress(self, extra: dict | None = None) -> None:
        pct = self.get_progress_pct()
        throughput = self.get_throughput()
        eta = self.get_eta_seconds()
        data = {
            "phase": self._phase,
            "completed": self._completed,
            "failed": self._failed,
            "progress_pct": f"{pct:.1f}%",
            "throughput": f"{throughput:.2f}/s",
            "eta": f"{eta:.0f}s" if eta else "unknown",
        }
        if extra:
            data.update(extra)
        logger.info("progress", **data)


import signal


class Orchestrator:
    """Coordinates the crawl phases."""

    def __init__(self, config: Config):
        self._config = config
        self._signal_handler = SignalHandler()
        self._fetcher = Fetcher(config)
        self._storage: Storage | None = None
        self._phase_governor: PhaseGovernor | None = None
        self._health_checker: HealthChecker | None = None
        self._metrics_pusher: MetricsPusher | None = None
        self._log_shipper: LogShipper | None = None
        self._rate_limit_monitor: RateLimitMonitor | None = None
        self._aggregation_engine: AggregationEngine | None = None
        self._checkpoints: dict[str, CheckpointManager] = {}
        self._trackers: dict[str, ProgressTracker] = {}
        self._phase_start_times: dict[str, float] = {}

    def _make_checkpoint(self, phase: str) -> CheckpointManager:
        if phase not in self._checkpoints:
            self._checkpoints[phase] = CheckpointManager(
                self._config.checkpoint.dir, phase
            )
        return self._checkpoints[phase]

    def _make_tracker(self, phase: str, total: int | None = None) -> ProgressTracker:
        if phase not in self._trackers:
            self._trackers[phase] = ProgressTracker(phase, total)
        return self._trackers[phase]

    async def _update_metrics_loop(self):
        """Periodically update Prometheus gauges."""
        while True:
            try:
                # Update table counts
                if self._storage:
                    list_count = self._storage.get_list_count()
                    info_count = self._storage.get_info_count()
                    card_count = self._storage.get_card_count()
                    
                    LIST_COUNT.set(list_count)
                    INFO_COUNT.set(info_count)
                    CARD_COUNT.set(card_count)
                    
                    # Update phase progress for phases 2/3 based on list count
                    list_total = list_count if list_count > 0 else None
                    
                    if list_total:
                        phase1_progress = self._phase_governor.get_progress("list") if self._phase_governor else 0
                        PHASE_PROGRESS_PCT.labels(phase="list").set(phase1_progress)
                        
                        # Only set phase 2/3 progress if they have data or are running
                        if info_count > 0 or (self._phase_governor and self._phase_governor.get_state("info") != PhaseState.PENDING):
                            PHASE_PROGRESS_PCT.labels(phase="info").set((info_count / list_total) * 100)
                        if card_count > 0 or (self._phase_governor and self._phase_governor.get_state("card") != PhaseState.PENDING):
                            PHASE_PROGRESS_PCT.labels(phase="card").set((card_count / list_total) * 100)
                
                # Update phase status
                if self._phase_governor:
                    for phase_name in ["list", "info", "card"]:
                        state = self._phase_governor.get_state(phase_name)
                        PHASE_STATUS.labels(phase=phase_name).set(state.value if hasattr(state, 'value') else int(state))
                
                # Update trackers
                for phase_name, tracker in self._trackers.items():
                    ACTIVE_WORKERS.labels(phase=phase_name).set(tracker.active_count if hasattr(tracker, 'active_count') else 0)
                    THROUGHPUT_MODELS_PER_SECOND.labels(phase=phase_name).set(tracker.get_throughput())
                
                # Update aggregated gauges
                if self._aggregation_engine:
                    aggregates = self._aggregation_engine.get_current_aggregates()
                    
                    # Update phase runtime
                    for phase_name, start_time in self._phase_start_times.items():
                        elapsed = time.time() - start_time
                        PHASE_RUNTIME_SECONDS.labels(phase=phase_name).set(elapsed)
                        
                        # Calculate ETA for phases 2/3
                        if phase_name in ["info", "card"] and list_total:
                            if phase_name == "info":
                                current_count = info_count
                            else:
                                current_count = card_count
                            
                            if current_count > 0:
                                pct = (current_count / list_total) * 100
                                if pct > 0:
                                    eta = (elapsed / pct) * (100 - pct)
                                    PHASE_ETA_SECONDS.labels(phase=phase_name).set(eta)
                
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error("metrics_update_error", error=str(e))
            await asyncio.sleep(30)

    async def run(self, phase: str = "all") -> None:
        """Run the crawl. Phase can be 'all', 'list', 'info', or 'card'."""
        await self._fetcher.start()

        # Initialize storage with a dummy checkpoint (will be replaced per-phase)
        dummy_checkpoint = self._make_checkpoint("init")
        self._storage = Storage(self._config, dummy_checkpoint)
        self._storage.start()
        self._phase_governor = PhaseGovernor(self._config, self._storage)
        self._health_checker = HealthChecker(self._config, self._storage)

        # Start monitoring
        self._metrics_pusher = MetricsPusher(self._config)
        await self._metrics_pusher.start()
        self._log_shipper = LogShipper(self._config)
        await self._log_shipper.start()

        # Start rate limit monitor
        self._rate_limit_monitor = RateLimitMonitor(self._config)
        await self._rate_limit_monitor.start()

        # Start aggregation engine
        self._aggregation_engine = AggregationEngine(interval_seconds=300)
        await self._aggregation_engine.start()

        # Start query server (for web UI and API access to data)
        self._query_server = QueryServer(self._config, self._storage)
        await self._query_server.start(8001)

        # Start periodic metrics update
        self._metrics_task = asyncio.create_task(self._update_metrics_loop())

        # Health check
        healthy, issues = self._health_checker.is_healthy()
        if not healthy:
            logger.error("health_check_failed", issues=issues)
            await self._log_shipper.log("error", "Health check failed", issues=str(issues))
            logger.warning("proceeding_despite_health_issues")

        self._signal_handler.install()

        phases_to_run = []
        if phase == "all":
            phases_to_run = ["list", "info", "card"]
        else:
            phases_to_run = [phase]

        try:
            for phase_name in phases_to_run:
                if self._signal_handler.should_shutdown:
                    break
                await self._run_phase(phase_name)
                # Check for phase transitions when running all
                if phase == "all" and phase_name == "list":
                    if self._phase_governor.can_start_info():
                        logger.info("phase2_threshold_reached", pct=self._phase_governor.get_progress("list"))
                        await self._log_shipper.log("info", "Phase 2 threshold reached", pct=self._phase_governor.get_progress("list"))
                if phase == "all" and phase_name == "info":
                    if self._phase_governor.can_start_card():
                        logger.info("phase2_complete_starting_phase3")
                        await self._log_shipper.log("info", "Phase 2 complete, starting Phase 3")
        except Exception as e:
            logger.error("orchestrator_error", error=str(e), exc_info=True)
            await self._log_shipper.log("error", f"Orchestrator error: {e}")
            raise
        finally:
            await self._fetcher.close()
            if self._storage:
                self._storage.close()
            if self._metrics_pusher:
                await self._metrics_pusher.stop()
            if self._log_shipper:
                await self._log_shipper.stop()

    async def _run_phase(self, phase_name: str) -> None:
        """Run a single phase."""
        state = self._phase_governor.get_state(phase_name)
        if state == PhaseState.COMPLETE:
            logger.info("phase_already_complete", phase=phase_name)
            return
        if state == PhaseState.RUNNING:
            logger.info("phase_already_running_resuming", phase=phase_name)

        self._phase_governor.set_state(phase_name, PhaseState.RUNNING)
        self._phase_start_times[phase_name] = time.time()
        logger.info("phase_started", phase=phase_name)
        await self._log_shipper.log("info", f"Phase {phase_name} started")

        try:
            if phase_name == "list":
                await self._run_phase1_list()
            elif phase_name == "info":
                await self._run_phase2_info()
            elif phase_name == "card":
                await self._run_phase3_card()
            self._phase_governor.set_state(phase_name, PhaseState.COMPLETE)
            logger.info("phase_complete", phase=phase_name)
            await self._log_shipper.log("info", f"Phase {phase_name} complete")
        except Exception as e:
            self._phase_governor.set_state(phase_name, PhaseState.FAILED)
            logger.error("phase_failed", phase=phase_name, error=str(e), exc_info=True)
            await self._log_shipper.log("error", f"Phase {phase_name} failed: {e}")
            raise

    async def _run_phase1_list(self) -> None:
        """Run Phase 1: list all models."""
        checkpoint = self._make_checkpoint("phase1_list")
        tracker = self._make_tracker("phase1_list", total=None)
        max_items = self._config.max_items

        page = checkpoint.page
        total_fetched = checkpoint.count

        fetcher = Phase1ListModelFetcher(
            self._fetcher, self._storage, checkpoint, max_items=max_items
        )

        # Set active workers
        ACTIVE_WORKERS.labels(phase="list").set(
            self._config.rate_limiting.max_concurrent_requests
        )

        def get_params(cursor: str | None) -> dict:
            params = {
                "sort": self._config.huggingface.sort_field,
                "direction": self._config.huggingface.sort_direction,
                "limit": self._config.huggingface.page_size,
            }
            if cursor:
                params["cursor"] = cursor
            return params

        result = await fetcher.run(get_params, self._signal_handler)
        tracker.increment(result[0] if isinstance(result, tuple) else 0)

        # Clear active workers when done
        ACTIVE_WORKERS.labels(phase="list").set(0)
        
        self._phase_governor.set_progress("list", 100.0 if not max_items else (total_fetched / max_items) * 100)
        logger.info("phase1_done", total_fetched=tracker.completed, pages=page)

    async def _run_phase2_info(self) -> None:
        """Run Phase 2: fetch info for each model."""
        checkpoint = self._make_checkpoint("phase2_info")
        all_ids = self._storage.get_all_model_ids()
        existing_ids = self._storage.get_info_model_ids()

        pending_ids = [mid for mid in all_ids if mid not in existing_ids]
        if self._config.max_items:
            pending_ids = pending_ids[:self._config.max_items]

        tracker = self._make_tracker("phase2_info", total=len(pending_ids))

        fetcher = Phase2ModelInfoFetcher(
            self._fetcher, self._storage, checkpoint,
            max_concurrent=self._config.rate_limiting.max_concurrent_requests,
            max_items=self._config.max_items,
        )

        # Set active workers
        ACTIVE_WORKERS.labels(phase="info").set(
            self._config.rate_limiting.max_concurrent_requests
        )

        completed, failed = await fetcher.run(pending_ids, self._signal_handler)
        tracker.increment(completed, failed)

        # Clear active workers when done
        ACTIVE_WORKERS.labels(phase="info").set(0)

        self._phase_governor.set_progress("info", tracker.get_progress_pct())
        logger.info("phase2_done", total_fetched=tracker.completed, failed=tracker.failed)

    async def _run_phase3_card(self) -> None:
        """Run Phase 3: fetch README for each model."""
        checkpoint = self._make_checkpoint("phase3_card")
        all_ids = self._storage.get_all_model_ids()
        existing_ids = self._storage.get_card_model_ids()

        pending_ids = [mid for mid in all_ids if mid not in existing_ids]
        if self._config.max_items:
            pending_ids = pending_ids[:self._config.max_items]

        tracker = self._make_tracker("phase3_card", total=len(pending_ids))

        fetcher = Phase3ModelCardFetcher(
            self._fetcher, self._storage, checkpoint,
            max_concurrent=self._config.rate_limiting.max_concurrent_requests,
            max_items=self._config.max_items,
        )

        # Set active workers
        ACTIVE_WORKERS.labels(phase="card").set(
            self._config.rate_limiting.max_concurrent_requests
        )

        completed, failed = await fetcher.run(pending_ids, self._signal_handler)
        tracker.increment(completed, failed)

        # Clear active workers when done
        ACTIVE_WORKERS.labels(phase="card").set(0)

        self._phase_governor.set_progress("card", tracker.get_progress_pct())
        logger.info("phase3_done", total_fetched=tracker.completed, failed=tracker.failed)
