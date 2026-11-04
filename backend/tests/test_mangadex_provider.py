"""
Comprehensive test suite for MangaDex provider, client, and API routes.
All tests are 100% mocked with zero external internet dependencies.
"""

import json
from datetime import datetime
import httpx
import pytest
from fastapi.testclient import TestClient

from main import app
from providers.base import (
    BaseMangaProvider,
    ProviderNetworkError,
    ProviderNotFoundError,
    ProviderRateLimitError,
)
from providers.mangadex.client import MangaDexHttpClient
from providers.mangadex.provider import MangaDexProvider
from providers.registry import ProviderRegistry


# ==============================================================================
# Sample Mock Payloads (MangaDex API format)
# ==============================================================================

MOCK_MANGA_PAYLOAD = {
    "result": "ok",
    "response": "entity",
    "data": {
        "id": "e896c48c-3150-437d-ba57-d8567eb399ae",
        "type": "manga",
        "attributes": {
            "title": {"en": "Chainsaw Man", "ja-ro": "Chainsaw Man"},
            "altTitles": [
                {"ru": "Человек-бензопила"},
                {"ja": "チェンソーマン"},
            ],
            "description": {
                "en": "Broke young man living with a chainsaw demon.",
                "ru": "История о парне Дэндзи и демоне бензопилы.",
            },
            "status": "ongoing",
            "year": 2018,
            "availableTranslatedLanguages": ["en", "ru", "pt-br"],
            "tags": [
                {
                    "id": "tag-1",
                    "type": "tag",
                    "attributes": {"name": {"en": "Action"}},
                },
                {
                    "id": "tag-2",
                    "type": "tag",
                    "attributes": {"name": {"en": "Supernatural"}},
                },
            ],
        },
        "relationships": [
            {
                "id": "author-1",
                "type": "author",
                "attributes": {"name": "Tatsuki Fujimoto"},
            },
            {
                "id": "artist-1",
                "type": "artist",
                "attributes": {"name": "Tatsuki Fujimoto"},
            },
            {
                "id": "cover-1",
                "type": "cover_art",
                "attributes": {"fileName": "chainsaw-cover.jpg"},
            },
        ],
    },
}

MOCK_SEARCH_PAYLOAD = {
    "result": "ok",
    "response": "collection",
    "data": [MOCK_MANGA_PAYLOAD["data"]],
    "limit": 20,
    "offset": 0,
    "total": 1,
}

MOCK_MANGA_NO_RU = {
    "id": "english-only-manga-id",
    "type": "manga",
    "attributes": {
        "title": {"en": "English Only Manga"},
        "altTitles": [],
        "description": {"en": "Only in English"},
        "status": "ongoing",
        "year": 2023,
        "availableTranslatedLanguages": ["en", "ja"],
        "tags": [],
    },
    "relationships": [],
}

MOCK_SEARCH_WITH_MIXED_LANGUAGES = {
    "result": "ok",
    "response": "collection",
    "data": [MOCK_MANGA_PAYLOAD["data"], MOCK_MANGA_NO_RU],
    "limit": 20,
    "offset": 0,
    "total": 2,
}

MOCK_EMPTY_SEARCH_PAYLOAD = {
    "result": "ok",
    "response": "collection",
    "data": [],
    "limit": 20,
    "offset": 0,
    "total": 0,
}

MOCK_CHAPTERS_PAYLOAD = {
    "result": "ok",
    "response": "collection",
    "data": [
        {
            "id": "ch-1-id",
            "type": "chapter",
            "attributes": {
                "volume": "1",
                "chapter": "1",
                "title": "Пёс и бензопила",
                "translatedLanguage": "ru",
                "publishAt": "2020-01-01T12:00:00+00:00",
            },
            "relationships": [
                {
                    "id": "group-1",
                    "type": "scanlation_group",
                    "attributes": {"name": "Manga Translators Gang"},
                }
            ],
        },
        {
            "id": "ch-1-5-id",
            "type": "chapter",
            "attributes": {
                "volume": "1",
                "chapter": "1.5",
                "title": "Бонус: Дневник Почиты",
                "translatedLanguage": "ru",
                "publishAt": "2020-01-05T12:00:00+00:00",
            },
            "relationships": [],
        },
        {
            "id": "ch-special-id",
            "type": "chapter",
            "attributes": {
                "volume": None,
                "chapter": None,  # Special/unnumbered chapter
                "title": "Экстра-пролог",
                "translatedLanguage": "ru",
                "publishAt": "2020-01-06T12:00:00+00:00",
            },
            "relationships": [],
        },
    ],
    "limit": 100,
    "offset": 0,
    "total": 3,
}

MOCK_AT_HOME_PAYLOAD = {
    "result": "ok",
    "baseUrl": "https://node.mangadex.network",
    "chapter": {
        "hash": "abc123hash",
        "data": ["page1.png", "page2.png", "page3.png"],
        "dataSaver": ["page1.jpg", "page2.jpg", "page3.jpg"],
    },
}


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def mock_mangadex():
    """Create a MangaDexProvider wired to a custom mock transport."""

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        path = request.url.path

        if path == "/manga" and request.method == "GET":
            # Assert query params enforce availableTranslatedLanguage[]=ru
            ru_langs = request.url.params.get_list("availableTranslatedLanguage[]")
            if "ru" not in ru_langs:
                return httpx.Response(400, json={"errors": [{"status": 400, "detail": "Missing Russian language filter"}]})

            query = request.url.params.get("title", "")
            if "empty" in query:
                return httpx.Response(200, json=MOCK_EMPTY_SEARCH_PAYLOAD)
            if "mixed" in query:
                return httpx.Response(200, json=MOCK_SEARCH_WITH_MIXED_LANGUAGES)
            return httpx.Response(200, json=MOCK_SEARCH_PAYLOAD)

        if path == "/manga/not-found-id":
            return httpx.Response(404, json={"errors": [{"status": 404, "detail": "Manga not found"}]})

        if path.startswith("/manga/") and path.endswith("/feed"):
            # Assert translatedLanguage[]=ru is strictly passed
            feed_langs = request.url.params.get_list("translatedLanguage[]")
            if "ru" not in feed_langs:
                return httpx.Response(400, json={"errors": [{"status": 400, "detail": "Only Russian is allowed"}]})

            manga_id = path.split("/")[2]
            if manga_id == "no-ru-chapters-id":
                return httpx.Response(200, json=MOCK_EMPTY_SEARCH_PAYLOAD)
            return httpx.Response(200, json=MOCK_CHAPTERS_PAYLOAD)

        if path.startswith("/manga/"):
            return httpx.Response(200, json=MOCK_MANGA_PAYLOAD)

        if path.startswith("/at-home/server/"):
            ch_id = path.split("/")[-1]
            if ch_id == "not-found-chapter":
                return httpx.Response(404, json={"errors": [{"status": 404, "detail": "Chapter not found"}]})
            return httpx.Response(200, json=MOCK_AT_HOME_PAYLOAD)

        return httpx.Response(404, text="Not Found")

    transport = httpx.MockTransport(handler)
    mock_http_client = httpx.AsyncClient(transport=transport, base_url="https://api.mangadex.org")
    client = MangaDexHttpClient(client=mock_http_client, min_request_interval=0.0)
    provider = MangaDexProvider(client=client)
    return provider


# ==============================================================================
# 1. Search Tests
# ==============================================================================

@pytest.mark.anyio
async def test_search_success(mock_mangadex: MangaDexProvider):
    res = await mock_mangadex.search(query="Chainsaw Man", page=1, limit=10)
    assert res.provider_id == "mangadex"
    assert res.total == 1
    assert len(res.items) == 1
    assert res.has_next is False

    item = res.items[0]
    assert item.provider_manga_id == "e896c48c-3150-437d-ba57-d8567eb399ae"
    assert item.title == "Chainsaw Man"
    assert "Человек-бензопила" in item.alt_titles
    assert item.description == "История о парне Дэндзи и демоне бензопилы."
    assert item.status == "ongoing"
    assert item.release_year == 2018
    assert item.authors == ["Tatsuki Fujimoto"]
    assert item.artists == ["Tatsuki Fujimoto"]
    assert "Action" in item.genres
    assert "Supernatural" in item.genres
    assert item.cover_url == "https://uploads.mangadex.org/covers/e896c48c-3150-437d-ba57-d8567eb399ae/chainsaw-cover.jpg.512.jpg"
    assert item.source_url == "https://mangadex.org/title/e896c48c-3150-437d-ba57-d8567eb399ae"
    assert item.available_languages == ["ru"]


@pytest.mark.anyio
async def test_search_filters_out_manga_without_russian_translation(mock_mangadex: MangaDexProvider):
    """Ensure search results do not return titles that lack Russian translations."""
    res = await mock_mangadex.search(query="mixed query", page=1, limit=10)
    assert res.total == 2
    # Only the manga with Russian translation is retained
    assert len(res.items) == 1
    assert res.items[0].provider_manga_id == "e896c48c-3150-437d-ba57-d8567eb399ae"


@pytest.mark.anyio
async def test_search_rejects_non_russian_language(mock_mangadex: MangaDexProvider):
    """Direct provider call rejects non-ru language filter."""
    with pytest.raises(ValueError, match="Onigiri only supports 'ru'"):
        await mock_mangadex.search(query="Chainsaw", languages=["en"])


@pytest.mark.anyio
async def test_search_empty(mock_mangadex: MangaDexProvider):
    res = await mock_mangadex.search(query="empty query", page=1, limit=10)
    assert res.total == 0
    assert len(res.items) == 0
    assert res.has_next is False


# ==============================================================================
# 2. Details Tests
# ==============================================================================

@pytest.mark.anyio
async def test_get_manga_details_success(mock_mangadex: MangaDexProvider):
    manga = await mock_mangadex.get_manga_details("e896c48c-3150-437d-ba57-d8567eb399ae")
    assert manga.provider_manga_id == "e896c48c-3150-437d-ba57-d8567eb399ae"
    assert manga.title == "Chainsaw Man"
    assert manga.release_year == 2018
    assert manga.available_languages == ["ru"]


# ==============================================================================
# 3. Chapters & Numbering Tests
# ==============================================================================

@pytest.mark.anyio
async def test_get_chapters_ru_success(mock_mangadex: MangaDexProvider):
    res = await mock_mangadex.get_chapters("e896c48c-3150-437d-ba57-d8567eb399ae", language="ru")
    assert res.total == 3
    assert len(res.chapters) == 3

    # Chapter 1 (standard integer number)
    ch1 = res.chapters[0]
    assert ch1.chapter_number_raw == "1"
    assert ch1.chapter_number_numeric == 1.0
    assert ch1.is_special is False
    assert ch1.volume_number == 1
    assert ch1.language == "ru"
    assert ch1.title == "Пёс и бензопила"
    assert ch1.scanlation_group == "Manga Translators Gang"
    assert isinstance(ch1.published_at, datetime)

    # Chapter 1.5 (decimal fractional chapter)
    ch1_5 = res.chapters[1]
    assert ch1_5.chapter_number_raw == "1.5"
    assert ch1_5.chapter_number_numeric == 1.5
    assert ch1_5.is_special is False
    assert ch1_5.title == "Бонус: Дневник Почиты"

    # Special unnumbered chapter
    ch_sp = res.chapters[2]
    assert ch_sp.chapter_number_raw is None
    assert ch_sp.chapter_number_numeric is None
    assert ch_sp.is_special is True
    assert ch_sp.title == "Экстра-пролог"


@pytest.mark.anyio
async def test_get_chapters_rejects_non_russian_language(mock_mangadex: MangaDexProvider):
    """Direct provider call rejects non-ru language parameter."""
    with pytest.raises(ValueError, match="Onigiri only supports 'ru'"):
        await mock_mangadex.get_chapters("e896c48c-3150-437d-ba57-d8567eb399ae", language="en")


@pytest.mark.anyio
async def test_get_chapters_no_translations(mock_mangadex: MangaDexProvider):
    """When no Russian translations exist for manga feed."""
    res = await mock_mangadex.get_chapters("no-ru-chapters-id", language="ru")
    assert res.total == 0
    assert len(res.chapters) == 0


# ==============================================================================
# 4. Pages & MangaDex@Home Delivery Tests
# ==============================================================================

@pytest.mark.anyio
async def test_get_chapter_pages_standard(mock_mangadex: MangaDexProvider):
    res = await mock_mangadex.get_chapter_pages("ch-1-id", data_saver=False)
    assert res.provider_chapter_id == "ch-1-id"
    assert res.data_saver is False
    assert res.expires_at is None  # Do not invent expiration date
    assert len(res.pages) == 3

    p1 = res.pages[0]
    assert p1.page_number == 1
    assert p1.image_url == "https://node.mangadex.network/data/abc123hash/page1.png"


@pytest.mark.anyio
async def test_get_chapter_pages_data_saver(mock_mangadex: MangaDexProvider):
    res = await mock_mangadex.get_chapter_pages("ch-1-id", data_saver=True)
    assert res.data_saver is True
    assert res.expires_at is None
    assert len(res.pages) == 3

    p1 = res.pages[0]
    assert p1.page_number == 1
    assert p1.image_url == "https://node.mangadex.network/data-saver/abc123hash/page1.jpg"


@pytest.mark.anyio
async def test_get_chapter_pages_rejects_insecure_or_invalid_base_url():
    """Verify that insecure (HTTP) or missing baseUrl is rejected with ProviderNetworkError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result": "ok",
                "baseUrl": "http://insecure.node.network",  # Insecure HTTP
                "chapter": {"hash": "abc", "data": ["p1.jpg"]},
            },
        )

    transport = httpx.MockTransport(handler)
    client = MangaDexHttpClient(client=httpx.AsyncClient(transport=transport), min_request_interval=0.0)
    provider = MangaDexProvider(client=client)

    with pytest.raises(ProviderNetworkError, match="Insecure or invalid baseUrl"):
        await provider.get_chapter_pages("ch-1-id")


# ==============================================================================
# 5. Error Handling Tests (404, 429, Timeout, 500)
# ==============================================================================

@pytest.mark.anyio
async def test_not_found_404(mock_mangadex: MangaDexProvider):
    with pytest.raises(ProviderNotFoundError):
        await mock_mangadex.get_manga_details("not-found-id")


@pytest.mark.anyio
async def test_rate_limit_429():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "15"},
            json={"errors": [{"status": 429, "detail": "Rate limit exceeded"}]},
        )

    transport = httpx.MockTransport(handler)
    client = MangaDexHttpClient(client=httpx.AsyncClient(transport=transport), min_request_interval=0.0)
    provider = MangaDexProvider(client=client)

    with pytest.raises(ProviderRateLimitError) as exc_info:
        await provider.search("any")
    assert exc_info.value.retry_after == 15.0


@pytest.mark.anyio
async def test_timeout_handling():
    def handler(request: httpx.Request):
        raise httpx.ReadTimeout("Connection timed out", request=request)

    transport = httpx.MockTransport(handler)
    client = MangaDexHttpClient(client=httpx.AsyncClient(transport=transport), min_request_interval=0.0)
    provider = MangaDexProvider(client=client)

    with pytest.raises(ProviderNetworkError, match="timed out"):
        await provider.search("any")


@pytest.mark.anyio
async def test_server_500_handling():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    transport = httpx.MockTransport(handler)
    client = MangaDexHttpClient(client=httpx.AsyncClient(transport=transport), min_request_interval=0.0)
    provider = MangaDexProvider(client=client)

    with pytest.raises(ProviderNetworkError, match="500"):
        await provider.search("any")


# ==============================================================================
# 6. Provider Registry Lifecycle & Error Isolation Tests
# ==============================================================================

@pytest.mark.anyio
async def test_provider_registry_lifecycle():
    registry = ProviderRegistry()
    assert len(registry.list_providers()) == 0

    class DummyProvider(BaseMangaProvider):
        def __init__(self, pid: str):
            self._pid = pid
            self.closed = False

        @property
        def provider_id(self) -> str:
            return self._pid

        @property
        def name(self) -> str:
            return f"Dummy {self._pid}"

        async def search(self, *args, **kwargs):
            pass

        async def get_manga_details(self, *args, **kwargs):
            pass

        async def get_chapters(self, *args, **kwargs):
            pass

        async def get_chapter_pages(self, *args, **kwargs):
            pass

        async def close(self):
            self.closed = True

    p1 = DummyProvider("p1")
    p2 = DummyProvider("p2")
    registry.register(p1)
    registry.register(p2)

    assert registry.has("p1") is True
    assert registry.get("p1").name == "Dummy p1"
    assert len(registry.list_providers()) == 2

    # Verify safe closing of all providers
    await registry.close_all()
    assert p1.closed is True
    assert p2.closed is True


@pytest.mark.anyio
async def test_provider_registry_rejects_duplicate_registration():
    """Verify that registering a provider with an existing ID raises ValueError and does not overwrite."""
    registry = ProviderRegistry()

    class DummyProvider(BaseMangaProvider):
        @property
        def provider_id(self) -> str:
            return "same_id"

        @property
        def name(self) -> str:
            return "First"

        async def search(self, *args, **kwargs): pass
        async def get_manga_details(self, *args, **kwargs): pass
        async def get_chapters(self, *args, **kwargs): pass
        async def get_chapter_pages(self, *args, **kwargs): pass
        async def close(self): pass

    class DuplicateProvider(BaseMangaProvider):
        @property
        def provider_id(self) -> str:
            return "same_id"

        @property
        def name(self) -> str:
            return "Second"

        async def search(self, *args, **kwargs): pass
        async def get_manga_details(self, *args, **kwargs): pass
        async def get_chapters(self, *args, **kwargs): pass
        async def get_chapter_pages(self, *args, **kwargs): pass
        async def close(self): pass

    first = DummyProvider()
    second = DuplicateProvider()

    registry.register(first)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(second)

    # Confirm original provider remains untouched
    assert registry.get("same_id").name == "First"


@pytest.mark.anyio
async def test_provider_registry_close_isolates_exceptions():
    """Ensure that an error in one provider's close() does not prevent others from closing."""
    registry = ProviderRegistry()

    class FaultyProvider(BaseMangaProvider):
        @property
        def provider_id(self) -> str:
            return "faulty"

        @property
        def name(self) -> str:
            return "Faulty"

        async def search(self, *args, **kwargs):
            pass

        async def get_manga_details(self, *args, **kwargs):
            pass

        async def get_chapters(self, *args, **kwargs):
            pass

        async def get_chapter_pages(self, *args, **kwargs):
            pass

        async def close(self):
            raise RuntimeError("Failure in close")

    class HealthyProvider(BaseMangaProvider):
        def __init__(self):
            self.closed = False

        @property
        def provider_id(self) -> str:
            return "healthy"

        @property
        def name(self) -> str:
            return "Healthy"

        async def search(self, *args, **kwargs):
            pass

        async def get_manga_details(self, *args, **kwargs):
            pass

        async def get_chapters(self, *args, **kwargs):
            pass

        async def get_chapter_pages(self, *args, **kwargs):
            pass

        async def close(self):
            self.closed = True

    healthy = HealthyProvider()
    faulty = FaultyProvider()

    registry.register(faulty)
    registry.register(healthy)

    # Should not raise exception out of close_all
    await registry.close_all()
    assert healthy.closed is True


# ==============================================================================
# 7. FastAPI Route Integration Tests
# ==============================================================================

def test_api_routes_providers_integration(mock_mangadex: MangaDexProvider):
    # Set mock provider into app.state
    registry = ProviderRegistry()
    registry.register(mock_mangadex)
    app.state.provider_registry = registry

    client = TestClient(app)

    # 1. Health check still works
    r_health = client.get("/api/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "ok"

    # 2. List providers (only Russian language exposed)
    r_list = client.get("/api/providers")
    assert r_list.status_code == 200
    providers = r_list.json()["providers"]
    assert any(p["id"] == "mangadex" for p in providers)
    for p in providers:
        assert p.get("languages") == ["ru"]

    # 3. Search endpoint (Russian enforced, non-Russian rejected)
    r_search = client.get("/api/providers/mangadex/search?q=Chainsaw")
    assert r_search.status_code == 200
    search_data = r_search.json()
    assert search_data["total"] == 1
    assert search_data["items"][0]["title"] == "Chainsaw Man"
    assert search_data["items"][0]["available_languages"] == ["ru"]

    # Reject non-Russian search query
    r_search_en = client.get("/api/providers/mangadex/search?q=Chainsaw&lang=en")
    assert r_search_en.status_code == 400
    assert "Only Russian language" in r_search_en.json()["detail"]

    # 4. Manga details endpoint
    r_details = client.get("/api/providers/mangadex/manga/e896c48c-3150-437d-ba57-d8567eb399ae")
    assert r_details.status_code == 200
    details_data = r_details.json()
    assert details_data["title"] == "Chainsaw Man"
    assert "Человек-бензопила" in details_data["alt_titles"]
    assert details_data["available_languages"] == ["ru"]

    # 5. Chapters feed endpoint (Russian enforced, non-Russian rejected)
    r_ch = client.get("/api/providers/mangadex/manga/e896c48c-3150-437d-ba57-d8567eb399ae/chapters?lang=ru")
    assert r_ch.status_code == 200
    ch_data = r_ch.json()
    assert ch_data["total"] == 3
    assert ch_data["chapters"][0]["chapter_number_raw"] == "1"
    assert ch_data["chapters"][0]["language"] == "ru"
    assert ch_data["chapters"][1]["chapter_number_numeric"] == 1.5
    assert ch_data["chapters"][2]["is_special"] is True

    # Reject non-Russian chapter query via lang=en
    r_ch_en = client.get("/api/providers/mangadex/manga/e896c48c-3150-437d-ba57-d8567eb399ae/chapters?lang=en")
    assert r_ch_en.status_code == 400
    assert "Only Russian language" in r_ch_en.json()["detail"]

    # Reject non-Russian chapter query via language=en
    r_ch_en2 = client.get("/api/providers/mangadex/manga/e896c48c-3150-437d-ba57-d8567eb399ae/chapters?language=en")
    assert r_ch_en2.status_code == 400
    assert "Only Russian language" in r_ch_en2.json()["detail"]

    # 6. Chapter pages endpoint
    r_pg = client.get("/api/providers/mangadex/chapters/ch-1-id/pages?data_saver=true")
    assert r_pg.status_code == 200
    pg_data = r_pg.json()
    assert pg_data["data_saver"] is True
    assert pg_data["expires_at"] is None
    assert len(pg_data["pages"]) == 3
    assert "data-saver" in pg_data["pages"][0]["image_url"]

    # 7. 404 for unknown provider
    r_unknown = client.get("/api/providers/unknown_src/search?q=any")
    assert r_unknown.status_code == 404
