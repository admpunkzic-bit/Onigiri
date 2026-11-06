"""
Asynchronous HTTP client for Manga-Chan (im.manga-chan.me).
Handles retry with exponential backoff, rate limiting, circuit breaker,
and DLE response parsing.
"""

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote
import httpx

from providers.base import (
    ProviderNetworkError,
    ProviderNotFoundError,
    ProviderRateLimitError,
)

logger = logging.getLogger(__name__)

DEFAULT_MANGACHAN_BASE_URL = "https://im.manga-chan.me"
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Onigiri/0.1.0"
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=5.0)


class CircuitBreakerOpenError(ProviderNetworkError):
    """Raised when circuit breaker is active and requests are blocked."""
    pass


class MangaChanHttpClient:
    """
    Dedicated HTTP client for Manga-Chan with retry and circuit breaker.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_MANGACHAN_BASE_URL,
        user_agent: str = DEFAULT_USER_AGENT,
        min_request_interval: float = 0.5,
        max_retries: int = 3,
        backoff_factor: float = 1.5,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self._min_interval = min_request_interval
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._last_request_time = 0.0
        self._rate_lock = asyncio.Lock()

        # Circuit Breaker state
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._consecutive_failures = 0
        self._circuit_state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self._last_state_change = 0.0

        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            },
            follow_redirects=True,
        )
        self._owns_client = client is None

    async def _throttle(self) -> None:
        async with self._rate_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_request_time = time.monotonic()

    def _check_circuit_breaker(self) -> None:
        now = time.monotonic()
        if self._circuit_state == "OPEN":
            if (now - self._last_state_change) > self._recovery_timeout:
                self._circuit_state = "HALF_OPEN"
                logger.info("Manga-Chan circuit breaker entering HALF_OPEN state")
            else:
                raise CircuitBreakerOpenError(
                    "Manga-Chan source is temporarily marked down (circuit breaker OPEN)"
                )

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        if self._circuit_state != "CLOSED":
            self._circuit_state = "CLOSED"
            self._last_state_change = time.monotonic()
            logger.info("Manga-Chan circuit breaker reset to CLOSED")

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._circuit_state == "HALF_OPEN" or self._consecutive_failures >= self._failure_threshold:
            self._circuit_state = "OPEN"
            self._last_state_change = time.monotonic()
            logger.warning(
                "Manga-Chan circuit breaker opened after %d consecutive failures",
                self._consecutive_failures,
            )

    async def get_html(self, path: str, referer: Optional[str] = None) -> str:
        """
        Execute GET request to Manga-Chan with rate limiting, retries, and circuit breaker.
        """
        self._check_circuit_breaker()

        url = path if path.startswith("http") else f"{self.base_url}{path}"
        headers = {}
        if referer:
            headers["Referer"] = referer

        last_error: Optional[Exception] = None

        for attempt in range(1, self._max_retries + 1):
            await self._throttle()
            try:
                response = await self._client.get(url, headers=headers)

                if response.status_code == 200:
                    self._record_success()
                    return response.text

                if response.status_code == 404:
                    self._record_success()
                    raise ProviderNotFoundError(f"Resource not found on Manga-Chan: {url}")

                if response.status_code == 429:
                    raise ProviderRateLimitError("Rate limit exceeded on Manga-Chan", retry_after=5.0)

                # Transient server errors (500, 502, 503, 504)
                if response.status_code in (500, 502, 503, 504):
                    logger.warning(
                        "Manga-Chan transient error HTTP %d (attempt %d/%d) for %s",
                        response.status_code,
                        attempt,
                        self._max_retries,
                        url,
                    )
                    last_error = ProviderNetworkError(
                        f"Manga-Chan returned transient HTTP {response.status_code}"
                    )
                else:
                    last_error = ProviderNetworkError(
                        f"Manga-Chan unexpected HTTP status {response.status_code}"
                    )

            except (httpx.TimeoutException, httpx.RequestError) as exc:
                logger.warning(
                    "Manga-Chan request error %s (attempt %d/%d) for %s",
                    exc,
                    attempt,
                    self._max_retries,
                    url,
                )
                last_error = ProviderNetworkError(f"Manga-Chan network error: {exc}", original_error=exc)

            if attempt < self._max_retries:
                await asyncio.sleep(self._backoff_factor * attempt)

        self._record_failure()
        if isinstance(last_error, Exception):
            raise last_error
        raise ProviderNetworkError(f"Failed to fetch {url} after {self._max_retries} attempts")

    async def search(self, query: str) -> str:
        """Execute search on Manga-Chan."""
        encoded = quote(query.strip())
        path = f"/?do=search&subaction=search&story={encoded}"
        return await self.get_html(path)

    async def get_manga(self, manga_id_or_slug: str) -> str:
        """Fetch manga details page."""
        clean = manga_id_or_slug.strip().lstrip("/")
        if not clean.startswith("manga/"):
            clean = f"manga/{clean}"
        if not clean.endswith(".html"):
            clean = f"{clean}.html"
        return await self.get_html(f"/{clean}")

    async def get_chapter(self, chapter_id: str) -> str:
        """Fetch chapter reader page."""
        clean = chapter_id.strip().lstrip("/")
        if not clean.startswith("online/"):
            clean = f"online/{clean}"
        if not clean.endswith(".html"):
            clean = f"{clean}.html"
        return await self.get_html(f"/{clean}")

    async def close(self) -> None:
        """Close persistent HTTP client session."""
        if self._owns_client and not self._client.is_closed:
            await self._client.aclose()
