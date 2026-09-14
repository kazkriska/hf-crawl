import asyncio
import time
from contextlib import asynccontextmanager


class RateLimiter:
    """Token bucket rate limiter with asyncio semaphore for concurrency control."""

    def __init__(self, max_requests_per_second: int, max_concurrent: int):
        self._rate = max_requests_per_second
        self._period = 1.0 / max_requests_per_second if max_requests_per_second > 0 else 1.0
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._last_request = 0.0
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self, endpoint: str = "default"):
        """Context manager that waits for rate limit token and concurrency slot."""
        async with self._semaphore:
            async with self._lock:
                now = time.monotonic()
                wait_time = self._last_request + self._period - now
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                self._last_request = time.monotonic()
            try:
                yield
            finally:
                pass

    async def wait_for_retry_after(self, seconds: float):
        """Wait the exact duration returned by a 429 RateLimit header."""
        await asyncio.sleep(seconds)

    async def exponential_backoff(self, attempt: int, base: float = 1.0, max_seconds: float = 60.0):
        """Exponential backoff with jitter. attempt is 0-indexed."""
        import random
        delay = min(base * (2 ** attempt), max_seconds)
        jitter = random.uniform(0, delay * 0.1)
        await asyncio.sleep(delay + jitter)
