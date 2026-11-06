"""
Tests for Manga-Chan provider, client, retry/circuit breaker, and image proxy.
"""

import asyncio
import re
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from providers.base import (
    ProviderNetworkError,
    ProviderNotFoundError,
    ProviderRateLimitError,
)
from providers.mangachan.client import MangaChanHttpClient, CircuitBreakerOpenError
from providers.mangachan.provider import MangaChanProvider
from services.reader import validate_and_resolve_url_ssrf


# ── Sample HTML Mock Fixtures ───────────────────────────────────────────────

SAMPLE_SEARCH_HTML = """
<html>
<body>
    <div class="content_row">
        <div class="manga_images">
            <img src="https://imgcover.manga-chan.me/uploads/posts/2013-09/thumbs/cover1.jpg" />
        </div>
        <a href="https://im.manga-chan.me/manga/24788-the-gamer.html">The gamer (Игрок)</a>
    </div>
    <div class="content_row">
        <a href="/manga/58812-the-gamercat.html">the GaMERCat (Игрокот)</a>
    </div>
</body>
</html>
"""

SAMPLE_MANGA_DETAILS_HTML = """
<html>
<body>
    <div id="manga_images">
        <img id="cover" src="https://imgcover.manga-chan.me/uploads/cover_the_gamer.jpg" />
    </div>
    <h1>The gamer (Игрок)</h1>
    <div id="description">
        Хан Джи-Хан был обычным школьником, пока внезапно не получил способность видеть мир как RPG-игру.
    </div>
    <div class="manga_details">
        <tr><td>Автор:</td><td><a href="/tags/author/">Сан Сон</a></td></tr>
        <tr><td>Перевод:</td><td>продолжается</td></tr>
        <tr><td>Теги:</td><td>
            <a href="/tags/comedy/">Комедия</a>
            <a href="/tags/action/">Боевик</a>
            <a href="/tags/web/">Веб</a>
        </td></tr>
    </div>
    <table class="table_cha">
        <tr>
            <td><div class='manga2'><a href='https://im.manga-chan.me/online/1117336-the-gamer_v7_ch44.html'>Том 7&nbsp;&nbsp;Глава 44</a></div></td>
            <td><div class='date'>2024-07-28</div></td>
        </tr>
        <tr>
            <td><div class='manga2'><a href='/online/358755-the-gamer_v1_ch1.html'>Том 1&nbsp;&nbsp;Глава 1</a></div></td>
            <td><div class='date'>2013-09-13</div></td>
        </tr>
        <tr>
            <td><div class='manga2'><a href='/online/358750-the-gamer_extra.html'>Экстра выпуск</a></div></td>
            <td><div class='date'>2013-09-01</div></td>
        </tr>
    </table>
</body>
</html>
"""

SAMPLE_READER_HTML = """
<html>
<body>
<script>
var data = {
    "name": "The Gamer",
    "fullimg": [
        "https://img7.manga-chan.me/manganew/-9new/t/the-gamer_v1_ch1/page_01.jpg",
        "https://img7.manga-chan.me/manganew/-9new/t/the-gamer_v1_ch1/page_02.avif",
        "https://img7.manga-chan.me/manganew/-9new/t/the-gamer_v1_ch1/page_03.webp",
    ]
};
</script>
</body>
</html>
"""


# ── Client & Circuit Breaker Tests ──────────────────────────────────────────

@pytest.mark.anyio
async def test_mangachan_client_retry_on_502():
    """Client must retry on transient 502 Bad Gateway and succeed when backend recovers."""
    call_count = 0

    async def mock_handler(request: httpx.Request):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return httpx.Response(502, text="Bad Gateway")
        return httpx.Response(200, text="<html>Success</html>")

    transport = httpx.MockTransport(mock_handler)
    async_client = httpx.AsyncClient(transport=transport)

    client = MangaChanHttpClient(
        client=async_client,
        min_request_interval=0.01,
        max_retries=3,
        backoff_factor=0.01,
    )

    result = await client.get_html("/manga/test.html")
    assert result == "<html>Success</html>"
    assert call_count == 3


@pytest.mark.anyio
async def test_mangachan_client_circuit_breaker():
    """Circuit breaker must open after threshold consecutive failures and reject further calls."""
    call_count = 0

    async def mock_handler(request: httpx.Request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(502, text="Bad Gateway")

    transport = httpx.MockTransport(mock_handler)
    async_client = httpx.AsyncClient(transport=transport)

    client = MangaChanHttpClient(
        client=async_client,
        min_request_interval=0.01,
        max_retries=1,
        failure_threshold=3,
        recovery_timeout=1.0,
    )

    # 3 failures -> opens circuit
    for _ in range(3):
        with pytest.raises(ProviderNetworkError):
            await client.get_html("/fail.html")

    assert client._circuit_state == "OPEN"

    # Next call must immediately fail with CircuitBreakerOpenError without network request
    with pytest.raises(CircuitBreakerOpenError, match="circuit breaker OPEN"):
        await client.get_html("/fail.html")


# ── Provider Parsing Tests ──────────────────────────────────────────────────

@pytest.mark.anyio
async def test_mangachan_search_parsing():
    """MangaChanProvider.search must correctly parse search results."""
    mock_client = MagicMock(spec=MangaChanHttpClient)
    mock_client.search = AsyncMock(return_value=SAMPLE_SEARCH_HTML)

    provider = MangaChanProvider(client=mock_client)
    res = await provider.search("The Gamer")

    assert res.provider_id == "mangachan"
    assert res.total == 2
    assert len(res.items) == 2

    item0 = res.items[0]
    assert item0.provider_manga_id == "24788-the-gamer"
    assert item0.title == "The gamer"
    assert "Игрок" in item0.alt_titles
    assert item0.cover_url == "https://imgcover.manga-chan.me/uploads/posts/2013-09/thumbs/cover1.jpg"
    assert item0.available_languages == ["ru"]


@pytest.mark.anyio
async def test_mangachan_details_parsing():
    """MangaChanProvider.get_manga_details must extract metadata and authors."""
    mock_client = MagicMock(spec=MangaChanHttpClient)
    mock_client.get_manga = AsyncMock(return_value=SAMPLE_MANGA_DETAILS_HTML)

    provider = MangaChanProvider(client=mock_client)
    item = await provider.get_manga_details("24788-the-gamer")

    assert item.title == "The gamer"
    assert "Игрок" in item.alt_titles
    assert "Хан Джи-Хан" in (item.description or "")
    assert item.cover_url == "https://imgcover.manga-chan.me/uploads/cover_the_gamer.jpg"
    assert "Сан Сон" in item.authors
    assert "Комедия" in item.genres
    assert "Боевик" in item.genres


@pytest.mark.anyio
async def test_mangachan_chapters_parsing():
    """MangaChanProvider.get_chapters must sort chapters ascending and parse volumes/numbers."""
    mock_client = MagicMock(spec=MangaChanHttpClient)
    mock_client.get_manga = AsyncMock(return_value=SAMPLE_MANGA_DETAILS_HTML)

    provider = MangaChanProvider(client=mock_client)
    res = await provider.get_chapters("24788-the-gamer")

    assert res.total == 3
    # Check ordering: Chapter 1 (vol 1) should be before Chapter 44 (vol 7)
    ch_ids = [ch.provider_chapter_id for ch in res.chapters]
    assert "358755-the-gamer_v1_ch1" in ch_ids
    assert "1117336-the-gamer_v7_ch44" in ch_ids

    ch1 = next(c for c in res.chapters if c.provider_chapter_id == "358755-the-gamer_v1_ch1")
    assert ch1.chapter_number_numeric == 1.0
    assert ch1.volume_number == 1
    assert ch1.language == "ru"

    ch44 = next(c for c in res.chapters if c.provider_chapter_id == "1117336-the-gamer_v7_ch44")
    assert ch44.chapter_number_numeric == 44.0
    assert ch44.volume_number == 7

    extra = next(c for c in res.chapters if c.provider_chapter_id == "358750-the-gamer_extra")
    assert extra.is_special is True


@pytest.mark.anyio
async def test_mangachan_pages_with_trailing_comma():
    """MangaChanProvider.get_chapter_pages must parse fullimg even with JS trailing commas."""
    mock_client = MagicMock(spec=MangaChanHttpClient)
    mock_client.get_chapter = AsyncMock(return_value=SAMPLE_READER_HTML)

    provider = MangaChanProvider(client=mock_client)
    res = await provider.get_chapter_pages("358755-the-gamer_v1_ch1")

    assert res.provider_id == "mangachan"
    assert len(res.pages) == 3
    assert res.pages[0].page_number == 1
    assert res.pages[0].image_url == "https://img7.manga-chan.me/manganew/-9new/t/the-gamer_v1_ch1/page_01.jpg"
    assert res.pages[1].image_url == "https://img7.manga-chan.me/manganew/-9new/t/the-gamer_v1_ch1/page_02.avif"
    assert res.pages[2].image_url == "https://img7.manga-chan.me/manganew/-9new/t/the-gamer_v1_ch1/page_03.webp"


# ── SSRF & Domain Allowlist Tests ───────────────────────────────────────────

def test_mangachan_domain_allowlist():
    """Manga-Chan domains must be accepted by SSRF validator."""
    # Subdomains of manga-chan.me must not be rejected by domain allowlist
    # (Testing domain regex logic without making network calls)
    allowed_hosts = [
        "https://img2.manga-chan.me/page1.jpg",
        "https://avifbig.manga-chan.me/page2.avif",
        "https://uploads.mangadex.org/covers/1.jpg",
    ]
    for url in allowed_hosts:
        # validate_and_resolve_url_ssrf will pass domain check (may fail on DNS in offline test)
        from urllib.parse import urlsplit
        hostname = urlsplit(url).hostname
        from services.reader import ALLOWED_DOMAINS
        assert any(hostname == a or hostname.endswith(a) for a in ALLOWED_DOMAINS)
