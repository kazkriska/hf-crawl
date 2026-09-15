from __future__ import annotations
import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

import structlog

from src.config import Config
from src.metrics import (
    MODELS_FETCHED_TOTAL,
    PHASE_PROGRESS_PCT,
    PHASE_STATUS,
    ACTIVE_WORKERS,
    LIST_COUNT,
    INFO_COUNT,
    CARD_COUNT,
    THROUGHPUT_MODELS_PER_SECOND,
    DB_SIZE_BYTES,
    DISK_FREE_BYTES,
    RATE_LIMIT_REMAINING,
    RATE_LIMIT_HITS_TOTAL,
    REQUESTS_TOTAL,
    REQUEST_DURATION_SECONDS,
    BATCH_COMMIT_DURATION_SECONDS,
)

logger = structlog.get_logger(__name__)


class MetricsPusher:
    """Pushes Prometheus metrics to Pushgateway on the monitoring LXC."""

    def __init__(self, config: Config):
        self._config = config
        self._pushgateway_url = f"http://{config.monitoring.pushgateway_host}:{config.monitoring.pushgateway_port}"
        self._job_name = config.monitoring.job_name
        self._instance = config.monitoring.instance_name
        self._push_interval = config.monitoring.push_interval_seconds
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the periodic push loop."""
        if not self._config.monitoring.enabled:
            return
        self._running = True
        self._task = asyncio.create_task(self._push_loop())
        logger.info("metrics_pusher_started", pushgateway=self._pushgateway_url, interval=self._push_interval)

    async def stop(self) -> None:
        """Stop the push loop and do a final push."""
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Final push
        await self._push_metrics()
        logger.info("metrics_pusher_stopped")

    async def _push_loop(self) -> None:
        """Periodically push metrics to Pushgateway."""
        while self._running:
            try:
                await self._push_metrics()
            except Exception as e:
                logger.error("metrics_push_error", error=str(e))
            await asyncio.sleep(self._push_interval)

    async def _push_metrics(self) -> None:
        """Push all current metrics to Pushgateway."""
        from prometheus_client import CollectorRegistry, generate_latest

        registry = CollectorRegistry()

        # Register all metrics
        registry.register(MODELS_FETCHED_TOTAL)
        registry.register(REQUESTS_TOTAL)
        registry.register(RATE_LIMIT_HITS_TOTAL)
        registry.register(PHASE_PROGRESS_PCT)
        registry.register(LIST_COUNT)
        registry.register(INFO_COUNT)
        registry.register(CARD_COUNT)
        registry.register(PHASE_STATUS)
        registry.register(RATE_LIMIT_REMAINING)
        registry.register(DB_SIZE_BYTES)
        registry.register(DISK_FREE_BYTES)
        registry.register(ACTIVE_WORKERS)
        registry.register(THROUGHPUT_MODELS_PER_SECOND)
        registry.register(REQUEST_DURATION_SECONDS)
        registry.register(BATCH_COMMIT_DURATION_SECONDS)

        # Push to gateway
        try:
            from prometheus_client import push_to_gateway
            push_to_gateway(
                self._pushgateway_url,
                job=self._job_name,
                registry=registry,
                grouping_key={"instance": self._instance},
            )
            logger.debug("metrics_pushed", pushgateway=self._pushgateway_url)
        except Exception as e:
            logger.error("push_to_gateway_error", error=str(e), pushgateway=self._pushgateway_url)


class RateLimitMonitor:
    """Monitors HF API rate limit and logs it periodically."""

    def __init__(self, config: Config):
        self._config = config
        self._interval = 10  # seconds
        self._task: asyncio.Task | None = None

    async def start(self):
        self._task = asyncio.create_task(self._run())
        logger.info("rate_limit_monitor_started", interval=self._interval)

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self):
        import httpx
        import yaml

        while True:
            try:
                with open("/app/config/config.prod.yaml") as f:
                    config = yaml.safe_load(f)
                token = config.get("huggingface", {}).get("token", "")

                headers = {
                    "Authorization": f"Bearer {token}"
                } if token else {}

                async with httpx.AsyncClient(base_url="https://huggingface.co", headers=headers) as client:
                    resp = await client.get("/api/models?limit=1")

                    status = resp.status_code
                    ratelimit = resp.headers.get("ratelimit", "N/A")
                    remaining = ratelimit.split(";")[1].split("=")[1] if ";" in ratelimit and "=" in ratelimit else "N/A"
                    reset_time = ratelimit.split(";")[2].split("=")[1] if ";" in ratelimit and len(ratelimit.split(";")) > 2 else "N/A"

                    logger.info("rate_limit_check",
                        status=status,
                        remaining=remaining,
                        reset_in_seconds=reset_time,
                        ratelimit_header=ratelimit
                    )

                    # Also log to stdout/stderr for Docker logs
                    print(f"[RATE LIMIT] Status: {status} | Remaining: {remaining} | Reset in: {reset_time}s | Raw: {ratelimit}", flush=True)

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error("rate_limit_check_error", error=str(e))
                print(f"[RATE LIMIT ERROR] {e}", flush=True)

            await asyncio.sleep(self._interval)


class LogShipper:
    """Ships structured logs directly to Loki on the monitoring LXC."""

    def __init__(self, config: Config):
        self._config = config
        self._loki_url = f"http://{config.monitoring.loki_host}:{config.monitoring.loki_port}/loki/api/v1/push"
        self._job_name = config.monitoring.job_name
        self._instance = config.monitoring.instance_name
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=10000)
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the log shipping loop."""
        if not self._config.monitoring.enabled:
            return
        self._running = True
        self._task = asyncio.create_task(self._ship_loop())
        logger.info("log_shipper_started", loki=self._loki_url)

    async def stop(self) -> None:
        """Stop the log shipper and flush remaining logs."""
        if not self._running:
            return
        self._running = False
        # Flush remaining logs
        await self._flush_remaining()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("log_shipper_stopped")

    async def log(self, level: str, message: str, **kwargs: Any) -> None:
        """Queue a log entry for shipping to Loki."""
        if not self._running:
            return
        entry = {
            "level": level,
            "message": message,
            "timestamp": time.time_ns(),
            "instance": self._instance,
            **kwargs,
        }
        try:
            self._queue.put_nowait(entry)
        except asyncio.QueueFull:
            pass  # Drop log if queue is full

    async def _ship_loop(self) -> None:
        """Periodically ship queued logs to Loki."""
        batch: list[dict] = []
        while self._running:
            try:
                # Collect logs for batching
                while len(batch) < 100:
                    try:
                        entry = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                        batch.append(entry)
                    except asyncio.TimeoutError:
                        break

                if batch:
                    await self._push_logs(batch)
                    batch = []
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("log_ship_error", error=str(e))
                await asyncio.sleep(5)

    async def _flush_remaining(self) -> None:
        """Flush all remaining logs in the queue."""
        batch: list[dict] = []
        while not self._queue.empty():
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if batch:
            await self._push_logs(batch)

    async def _push_logs(self, logs: list[dict]) -> None:
        """Push a batch of logs to Loki."""
        import httpx

        streams: dict[str, list[list[str]]] = {}
        for entry in logs:
            level = entry.pop("level", "info")
            instance = entry.pop("instance", self._instance)
            timestamp_ns = str(entry.pop("timestamp", time.time_ns()))
            message = entry.pop("message", "")

            # Build stream key
            stream_key = f"job={self._job_name},level={level},instance={instance}"
            if stream_key not in streams:
                streams[stream_key] = []

            # Format: [timestamp_ns, message]
            streams[stream_key].append([timestamp_ns, message])

        payload = {
            "streams": [
                {
                    "stream": dict(pair.split("=", 1) for pair in key.split(",")),
                    "values": values,
                }
                for key, values in streams.items()
            ]
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self._loki_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=10.0,
                )
                if resp.status_code != 204:
                    logger.warning("loki_push_failed", status=resp.status_code, body=resp.text[:200])
        except Exception as e:
            logger.error("loki_push_error", error=str(e), loki=self._loki_url)
