"""
MangaLib HTTP Client.
Handles communication with MangaLib / Lib.social API with polite retry,
proper browser headers, and exception mapping.
"""

import asyncio
import logging
from typing import Any, Dict, Optional
import httpx

from providers.base import (
    ProviderError,
    ProviderNetworkError,
    ProviderNotFoundError,
    ProviderRateLimitError,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0
PRIMARY_API_URL = "https://api.lib.social"
SECONDARY_API_URL = "https://api.cdnlibs.org"

COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://mangalib.me/",
    "Origin": "https://mangalib.me",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}


class MangaLibHttpClient:
    """Async HTTP client for MangaLib / Lib.social API."""

    def __init__(
        self,
        base_url: str = PRIMARY_API_URL,
        fallback_base_url: str = SECONDARY_API_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.fallback_base_url = fallback_base_url.rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=4.0),
                headers=COMMON_HEADERS,
                follow_redirects=True,
            )
        return self._client

    async def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        max_retries: int = 2,
    ) -> Any:
        """Execute HTTP request with fallback domain, retry logic, and error mapping."""
        client = await self._get_client()
        normalized_path = path if path.startswith("/") else f"/{path}"

        hosts_to_try = [self.base_url, self.fallback_base_url]
        last_error: Optional[Exception] = None

        for host in hosts_to_try:
            full_url = f"{host}{normalized_path}"
            for attempt in range(1, max_retries + 1):
                try:
                    response = await client.request(method, full_url, params=params)

                    if response.status_code == 200:
                        return response.json()

                    if response.status_code == 404:
                        raise ProviderNotFoundError(f"MangaLib resource not found: {normalized_path}")

                    if response.status_code == 429:
                        retry_after = float(response.headers.get("Retry-After", 2.0))
                        if attempt < max_retries:
                            logger.warning("MangaLib rate limit hit, backing off %.1fs", retry_after)
                            await asyncio.sleep(retry_after)
                            continue
                        raise ProviderRateLimitError("MangaLib rate limit exceeded", retry_after=retry_after)

                    if response.status_code in (500, 502, 503, 504):
                        if attempt < max_retries:
                            await asyncio.sleep(1.0 * attempt)
                            continue
                        # If server error, will break to try fallback host
                        break

                    response.raise_for_status()
                    return response.json()

                except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as exc:
                    last_error = exc
                    if attempt < max_retries:
                        await asyncio.sleep(0.5)
                        continue
                    break

                except (ProviderNotFoundError, ProviderRateLimitError):
                    raise
                except Exception as exc:
                    last_error = exc
                    break

        if isinstance(last_error, ProviderError):
            raise last_error
        raise ProviderNetworkError(f"MangaLib request failed across hosts: {last_error}", original_error=last_error)

    async def close(self) -> None:
        """Close persistent HTTP session."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
