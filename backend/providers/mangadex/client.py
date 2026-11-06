"""
Asynchronous HTTP client for the official MangaDex REST API (api.mangadex.org).
Handles timeouts, connection pooling, rate limiting, and structured error mapping.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
import httpx

from providers.base import (
    ProviderNetworkError,
    ProviderNotFoundError,
    ProviderRateLimitError,
)

logger = logging.getLogger(__name__)

DEFAULT_MANGADEX_BASE_URL = "https://api.mangadex.org"
DEFAULT_USER_AGENT = "Onigiri/0.1.0 (https://onigiri.punk.uz)"
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)


class MangaDexHttpClient:
    """
    Dedicated client for communicating with the MangaDex REST API.
    Maintains a persistent httpx.AsyncClient session and applies controlled rate limiting.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_MANGADEX_BASE_URL,
        user_agent: str = DEFAULT_USER_AGENT,
        min_request_interval: float = 0.2,  # Target rate limiter ~5 req/s
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self._min_interval = min_request_interval
        self._last_request_time = 0.0
        self._rate_lock = asyncio.Lock()

        # Allow passing an existing client (useful for mock testing)
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
        )
        self._owns_client = client is None

    async def _throttle(self) -> None:
        """Ensure minimum delay between consecutive outbound requests."""
        async with self._rate_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_request_time = time.monotonic()

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute rate-throttled HTTP request and map status codes to typed exceptions."""
        await self._throttle()
        url = f"{self.base_url}{path}"

        try:
            response = await self._client.request(method, url, params=params)
        except httpx.TimeoutException as exc:
            logger.warning(f"MangaDex request timeout: {method} {url}")
            raise ProviderNetworkError(f"MangaDex request timed out: {exc}", original_error=exc) from exc
        except httpx.RequestError as exc:
            logger.error(f"MangaDex connection error: {method} {url}: {exc}")
            raise ProviderNetworkError(f"Failed to connect to MangaDex: {exc}", original_error=exc) from exc

        # Handle rate limits
        if response.status_code == 429:
            retry_after_header = response.headers.get("retry-after") or response.headers.get("x-ratelimit-retry-after")
            retry_after_val: Optional[float] = None
            if retry_after_header:
                try:
                    retry_after_val = float(retry_after_header)
                except (ValueError, TypeError):
                    retry_after_val = None
            logger.warning(f"MangaDex rate limit exceeded (HTTP 429). Retry-After: {retry_after_val}")
            raise ProviderRateLimitError(
                f"MangaDex rate limit exceeded. Retry after {retry_after_val or 'a few'} seconds.",
                retry_after=retry_after_val,
            )

        # Handle 404 Not Found
        if response.status_code == 404:
            raise ProviderNotFoundError(f"Requested resource not found on MangaDex: {path}")

        # Handle other HTTP errors
        if response.is_error:
            logger.error(f"MangaDex returned error {response.status_code}: {response.text[:200]}")
            raise ProviderNetworkError(
                f"MangaDex API error ({response.status_code}): {response.text[:200]}"
            )

        try:
            return response.json()
        except Exception as exc:
            raise ProviderNetworkError(f"MangaDex returned invalid JSON: {exc}", original_error=exc) from exc

    async def search_manga(
        self,
        title: str,
        limit: int = 20,
        offset: int = 0,
        languages: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Search manga by title with author, artist, and cover_art relationships."""
        params: List[tuple] = [
            ("title", title),
            ("limit", str(limit)),
            ("offset", str(offset)),
            ("includes[]", "cover_art"),
            ("includes[]", "author"),
            ("includes[]", "artist"),
        ]
        # Onigiri strictly requires Russian content ('ru')
        langs = languages if languages is not None else ["ru"]
        for lang in langs:
            if lang != "ru":
                raise ValueError(f"Language '{lang}' is not supported. Onigiri only supports 'ru'.")
            params.append(("availableTranslatedLanguage[]", "ru"))

        return await self._request("GET", "/manga", params=params)

    async def get_manga(self, manga_id: str) -> Dict[str, Any]:
        """Get single manga details with cover_art, author, and artist relationships."""
        params = [
            ("includes[]", "cover_art"),
            ("includes[]", "author"),
            ("includes[]", "artist"),
        ]
        return await self._request("GET", f"/manga/{manga_id}", params=params)

    async def get_manga_feed(
        self,
        manga_id: str,
        limit: int = 100,
        offset: int = 0,
        language: str = "ru",
    ) -> Dict[str, Any]:
        """Get chapters feed for a manga strictly in Russian language."""
        if language != "ru":
            raise ValueError(f"Language '{language}' is not supported. Onigiri only supports 'ru'.")
        params = [
            ("limit", str(limit)),
            ("offset", str(offset)),
            ("translatedLanguage[]", "ru"),
            ("order[chapter]", "asc"),
            ("includes[]", "scanlation_group"),
        ]
        return await self._request("GET", f"/manga/{manga_id}/feed", params=params)

    async def get_at_home_server(self, chapter_id: str) -> Dict[str, Any]:
        """Get MangaDex@Home base URL and file hashes for chapter pages, forcing port 443 for reliable SSL and caching."""
        return await self._request("GET", f"/at-home/server/{chapter_id}", params={"forcePort443": "true"})

    async def close(self) -> None:
        """Close underlying HTTP client."""
        if self._owns_client and not self._client.is_closed:
            await self._client.aclose()
