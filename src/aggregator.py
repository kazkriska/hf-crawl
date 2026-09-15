from __future__ import annotations
import asyncio
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def median(values: list[float]) -> float:
    """Calculate median of a list of values."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n % 2 == 0:
        return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2
    return sorted_vals[n // 2]


def mean(values: list[float]) -> float:
    """Calculate mean of a list of values."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def std_dev(values: list[float]) -> float:
    """Calculate population standard deviation."""
    if not values:
        return 0.0
    m = mean(values)
    variance = sum((x - m) ** 2 for x in values) / len(values)
    return math.sqrt(variance)


def percentile(values: list[float], pct: int) -> float:
    """Calculate percentile value."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = int(len(sorted_vals) * pct / 100)
    idx = min(idx, len(sorted_vals) - 1)
    return sorted_vals[idx]


@dataclass
class MetricSample:
    """A single metric sample."""
    value: float
    timestamp: float
    labels: dict[str, str] = field(default_factory=dict)


class MetricAggregator:
    """Aggregates raw metric samples into compressed representations."""
    
    def __init__(self, window_seconds: int = 300):
        self._window_seconds = window_seconds  # 5 minutes
        self._samples: dict[str, list[MetricSample]] = defaultdict(list)
        self._aggregates: dict[str, dict[str, Any]] = {}
    
    def add_sample(self, metric_name: str, value: float, labels: dict[str, str] | None = None):
        """Add a metric sample."""
        sample = MetricSample(
            value=value,
            timestamp=time.time(),
            labels=labels or {},
        )
        key = f"{metric_name}:{self._format_labels(labels)}"
        self._samples[key].append(sample)
    
    def _format_labels(self, labels: dict[str, str] | None) -> str:
        """Format labels for key."""
        if not labels:
            return ""
        return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
    
    def aggregate_window(self, metric_name: str, labels: dict[str, str] | None = None) -> dict[str, Any]:
        """Aggregate samples in current window."""
        key = f"{metric_name}:{self._format_labels(labels)}"
        samples = self._samples.get(key, [])
        
        if not samples:
            return {
                "median": 0.0,
                "mean": 0.0,
                "stddev": 0.0,
                "min": 0.0,
                "max": 0.0,
                "count": 0,
                "p95": 0.0,
                "p99": 0.0,
            }
        
        values = [s.value for s in samples]
        
        return {
            "median": median(values),
            "mean": mean(values),
            "stddev": std_dev(values),
            "min": min(values),
            "max": max(values),
            "count": len(values),
            "p95": percentile(values, 95),
            "p99": percentile(values, 99),
        }
    
    def clear_window(self, metric_name: str | None = None, labels: dict[str, str] | None = None):
        """Clear samples after aggregation."""
        if metric_name is None:
            self._samples.clear()
        else:
            key = f"{metric_name}:{self._format_labels(labels)}"
            self._samples.pop(key, None)
    
    def prune_old_samples(self, max_age_seconds: int = 300):
        """Remove samples older than max_age_seconds."""
        cutoff = time.time() - max_age_seconds
        for key in list(self._samples.keys()):
            self._samples[key] = [
                s for s in self._samples[key]
                if s.timestamp > cutoff
            ]
            if not self._samples[key]:
                del self._samples[key]


class AggregationEngine:
    """Main engine that runs aggregation periodically."""
    
    def __init__(self, interval_seconds: int = 300):
        self._interval = interval_seconds
        self._aggregator = MetricAggregator(window_seconds=interval_seconds)
        self._running = False
        self._task: asyncio.Task | None = None
    
    async def start(self):
        """Start the aggregation loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("aggregation_engine_started", interval=self._interval)
    
    async def stop(self):
        """Stop the aggregation loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("aggregation_engine_stopped")
    
    async def _run_loop(self):
        """Run aggregation loop."""
        while True:
            try:
                await asyncio.sleep(self._interval)
                self._aggregator.prune_old_samples(self._interval)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error("aggregation_loop_error", error=str(e))
    
    @property
    def aggregator(self) -> MetricAggregator:
        return self._aggregator
    
    def record_request_rate(self, phase: str, rate: float):
        """Record a request rate sample."""
        self._aggregator.add_sample(
            "requests_per_minute",
            rate,
            {"phase": phase}
        )
    
    def record_rate_limit_remaining(self, remaining: int):
        """Record rate limit remaining."""
        self._aggregator.add_sample(
            "rate_limit_remaining",
            float(remaining),
            {}
        )
    
    def record_rate_limit_quota(self, quota: int):
        """Record rate limit quota."""
        self._aggregator.add_sample(
            "rate_limit_quota",
            float(quota),
            {}
        )
    
    def get_current_aggregates(self) -> dict[str, Any]:
        """Get aggregates for all metrics."""
        return {
            "requests_per_minute": self._aggregator.aggregate_window("requests_per_minute"),
            "rate_limit_remaining": self._aggregator.aggregate_window("rate_limit_remaining"),
            "rate_limit_quota": self._aggregator.aggregate_window("rate_limit_quota"),
        }
