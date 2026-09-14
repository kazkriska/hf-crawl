from __future__ import annotations
import asyncio
import time
from collections.abc import Callable
from typing import Any

import httpx
import structlog

from src.config import Config
from src.metrics import (
    REQUESTS_TOTAL,
    RATE_LIMIT_HITS_TOTAL,
    RATE_LIMIT_REMAINING,
    REQUEST_DURATION_SECONDS,
)
from src.components.rate_limiter import RateLimiter

logger = structlog.get_logger(__name__)


class FetcherError(Exception):
    """Non-retryable fetch error."""

    def __init__(self, status: int, url: str, body: str = ""):
        self.status = status
        self.url = url
        self.body = body
        super().__init__(f"HTTP {status} for {url}: {body[:200]}")


class Fetcher:
    """Async HTTP client with rate limiting, retries, and HF-specific handling."""

    def __init__(self, config: Config):
        self._config = config
        self._rate_limiter = RateLimiter(
            max_requests_per_second=config.rate_limiting.max_requests_per_second,
            max_concurrent=config.rate_limiting.max_concurrent_requests,
        )
        self._client: httpx.AsyncClient | None = None
        self._endpoint_buckets: dict[str, str] = {
            "api/models": "api",
            "models": "api",
            "raw/main": "resolvers",
            "resolve": "resolvers",
        }

    async def start(self):
        headers = {
            "User-Agent": "hf-crawl/1.0 (research project; anonymous)",
            "Accept": "application/json",
        }
        token = self._config.huggingface.token
        if token:
            headers["Authorization"] = f"Bearer {token}"
            headers["User-Agent"] = "hf-crawl/1.0 (research project; authenticated)"
        self._client = httpx.AsyncClient(
            base_url=self._config.huggingface.base_url,
            headers=headers,
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )

    async def close(self):
        if self._client:
            await self._client.aclose()

    def _bucket_for(self, url: str) -> str:
        for key, bucket in self._endpoint_buckets.items():
            if key in url:
                return bucket
        return "api"

    async def get_json(self, url: str, params: dict | None = None, phase: str = "unknown") -> tuple[dict | None, dict]:
        """GET JSON with retries. Returns (data, response_headers). Raises FetcherError on permanent failure."""
        for attempt in range(self._config.rate_limiting.max_retries + 1):
            async with self._rate_limiter.acquire(url):
                start = time.monotonic()
                try:
                    resp = await self._client.get(url, params=params or {})
                    duration = time.monotonic() - start
                    endpoint = url.split("?")[0].rstrip("/")
                    status_code = str(resp.status_code)
                    REQUEST_DURATION_SECONDS.labels(endpoint=endpoint, status_code=status_code).observe(duration)
                    REQUESTS_TOTAL.labels(endpoint=endpoint, status_code=status_code).inc()

                    if resp.status_code == 200:
                        return resp.json(), dict(resp.headers)

                    if resp.status_code == 429:
                        RATE_LIMIT_HITS_TOTAL.labels(endpoint=endpoint).inc()
                        retry_after = self._parse_retry_after(resp)
                        bucket = self._bucket_for(url)
                        RATE_LIMIT_REMAINING.labels(bucket=bucket).set(0)
                        logger.warning("rate_limited", url=url, attempt=attempt, retry_after=retry_after)
                        if attempt < self._config.rate_limiting.max_retries:
                            await self._rate_limiter.wait_for_retry_after(retry_after)
                            continue
                        raise FetcherError(429, url, "rate limited")

                    if resp.status_code == 404:
                        raise FetcherError(404, url, "not found")

                    if resp.status_code == 403:
                        raise FetcherError(403, url, "forbidden/gated")

                    if 500 <= resp.status_code < 600:
                        logger.warning("server_error", url=url, status=resp.status_code, attempt=attempt)
                        if attempt < self._config.rate_limiting.max_retries:
                            await self._rate_limiter.exponential_backoff(
                                attempt,
                                base=self._config.rate_limiting.backoff_base_seconds,
                                max_seconds=self._config.rate_limiting.backoff_max_seconds,
                            )
                            continue
                        raise FetcherError(resp.status_code, url, "max retries on 5xx")

                    raise FetcherError(resp.status_code, url, f"unexpected status")

                except httpx.TimeoutException:
                    logger.warning("request_timeout", url=url, attempt=attempt)
                    if attempt < self._config.rate_limiting.max_retries:
                        await self._rate_limiter.exponential_backoff(attempt)
                        continue
                    raise FetcherError(0, url, "timeout after max retries")
                except httpx.ConnectError:
                    logger.warning("connection_error", url=url, attempt=attempt)
                    if attempt < self._config.rate_limiting.max_retries:
                        await self._rate_limiter.exponential_backoff(attempt)
                        continue
                    raise FetcherError(0, url, "connection error after max retries")

        raise FetcherError(0, url, "exhausted retries")

    async def get_text(self, url: str, phase: str = "unknown") -> tuple[str | None, dict]:
        """GET plain text (for README.md) with retries. Returns (text, response_headers)."""
        for attempt in range(self._config.rate_limiting.max_retries + 1):
            async with self._rate_limiter.acquire(url):
                start = time.monotonic()
                try:
                    resp = await self._client.get(url)
                    duration = time.monotonic() - start
                    endpoint = url.split("?")[0].rstrip("/")
                    status_code = str(resp.status_code)
                    REQUEST_DURATION_SECONDS.labels(endpoint=endpoint, status_code=status_code).observe(duration)
                    REQUESTS_TOTAL.labels(endpoint=endpoint, status_code=status_code).inc()

                    if resp.status_code == 200:
                        return resp.text, dict(resp.headers)

                    if resp.status_code == 429:
                        RATE_LIMIT_HITS_TOTAL.labels(endpoint=endpoint).inc()
                        retry_after = self._parse_retry_after(resp)
                        bucket = self._bucket_for(url)
                        RATE_LIMIT_REMAINING.labels(bucket=bucket).set(0)
                        if attempt < self._config.rate_limiting.max_retries:
                            await self._rate_limiter.wait_for_retry_after(retry_after)
                            continue
                        raise FetcherError(429, url, "rate limited")

                    if resp.status_code == 404:
                        raise FetcherError(404, url, "not found")

                    if resp.status_code == 403:
                        raise FetcherError(403, url, "forbidden/gated")

                    if 500 <= resp.status_code < 600:
                        if attempt < self._config.rate_limiting.max_retries:
                            await self._rate_limiter.exponential_backoff(attempt)
                            continue
                        raise FetcherError(resp.status_code, url, "max retries on 5xx")

                    raise FetcherError(resp.status_code, url, "unexpected status")

                except httpx.TimeoutException:
                    if attempt < self._config.rate_limiting.max_retries:
                        await self._rate_limiter.exponential_backoff(attempt)
                        continue
                    raise FetcherError(0, url, "timeout")
                except httpx.ConnectError:
                    if attempt < self._config.rate_limiting.max_retries:
                        await self._rate_limiter.exponential_backoff(attempt)
                        continue
                    raise FetcherError(0, url, "connection error")

        raise FetcherError(0, url, "exhausted retries")

    def _parse_retry_after(self, resp: httpx.Response) -> float:
        """Parse Retry-After or RateLimit header from Hugging Face."""
        rl = resp.headers.get("ratelimit-remaining")
        if rl is not None:
            try:
                return max(1.0, 60.0 / max(1, int(rl)))
            except (ValueError, ZeroDivisionError):
                pass
        retry_after = resp.headers.get("retry-after")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        return 5.0
