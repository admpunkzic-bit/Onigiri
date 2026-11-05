"""
Unit and integration tests for Unified Catalog Service and API endpoints.
Tests mapping from provider to canonical Onigiri schema, idempotency,
search, detail view, and graceful error handling.
"""

import sqlite3
from typing import List, Optional
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from database.connection import get_connection
from database.migrations import run_migrations
from main import app
from providers.base import (
    BaseMangaProvider,
    ProviderChapterItem,
    ProviderChaptersResult,
    ProviderMangaItem,
    ProviderNetworkError,
    ProviderPagesResult,
    ProviderRateLimitError,
    ProviderSearchResult,
)
from providers.registry import ProviderRegistry
from services.catalog import CatalogService


@pytest.fixture
def catalog_db(tmp_path):
    """Temporary SQLite database with migrations applied."""
    db_file = tmp_path / "test_catalog.db"
    conn = get_connection(db_file)
    run_migrations(conn)
    yield conn
    conn.close()


class DummyMockProvider(BaseMangaProvider):
    """Mock external provider returning predefined Russian-translated manga items."""

    def __init__(self, provider_id: str = "mangadex", name: str = "MangaDex Mock"):
        self._provider_id = provider_id
        self._name = name
        self.search_mock = AsyncMock()
        self.get_chapters_mock = AsyncMock(
            return_value=ProviderChaptersResult(
                provider_id=self._provider_id,
                provider_manga_id="default",
                chapters=[],
                total=0,
                page=1,
                limit=100,
                has_next=False,
            )
        )
        self.get_details_mock = AsyncMock(return_value=None)

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def name(self) -> str:
        return self._name

    async def search(
        self,
        query: str,
        page: int = 1,
        limit: int = 20,
        languages: Optional[List[str]] = None,
    ) -> ProviderSearchResult:
        return await self.search_mock(query, page, limit, languages)

    async def get_manga_details(self, provider_manga_id: str) -> ProviderMangaItem:
        return await self.get_details_mock(provider_manga_id)

    async def get_chapters(
        self,
        provider_manga_id: str,
        language: str = "ru",
        page: int = 1,
        limit: int = 100,
    ) -> ProviderChaptersResult:
        return await self.get_chapters_mock(provider_manga_id, language, page, limit)

    async def get_chapter_pages(
        self,
        provider_chapter_id: str,
        data_saver: bool = False,
    ) -> ProviderPagesResult:
        raise NotImplementedError

    async def close(self) -> None:
        pass


# ==============================================================================
# 1. Upsert Provider Manga & Idempotency Tests
# ==============================================================================

def test_upsert_provider_manga_creates_records(catalog_db: sqlite3.Connection):
    """Ensure new provider item inserts manga, manga_sources, authors, and genres."""
    service = CatalogService(conn=catalog_db)

    item = ProviderMangaItem(
        provider_id="mangadex",
        provider_manga_id="md-101",
        title="Человек-бензопила",
        alt_titles=["Chainsaw Man"],
        description="История о Дэндзи и Почите.",
        cover_url="https://example.com/csm.jpg",
        status="completed",
        release_year=2018,
        authors=["Tatsuki Fujimoto"],
        artists=["Tatsuki Fujimoto"],
        genres=["Боевик", "Сверхъестественное"],
        available_languages=["ru"],
        source_url="https://mangadex.org/title/md-101",
    )

    manga_id = service.upsert_provider_manga(item)
    assert manga_id > 0

    cursor = catalog_db.cursor()

    # Check manga table
    cursor.execute("SELECT * FROM manga WHERE id = ?", (manga_id,))
    manga_row = cursor.fetchone()
    assert manga_row is not None
    assert manga_row["title"] == "Человек-бензопила"
    assert manga_row["slug"] == "chelovek-benzopila"
    assert manga_row["original_title"] == "Chainsaw Man"
    assert manga_row["status"] == "completed"
    assert manga_row["release_year"] == 2018

    # Check manga_sources table
    cursor.execute("SELECT * FROM manga_sources WHERE manga_id = ?", (manga_id,))
    sources = cursor.fetchall()
    assert len(sources) == 1
    assert sources[0]["source_name"] == "mangadex"
    assert sources[0]["source_manga_id"] == "md-101"

    # Check authors and roles
    cursor.execute(
        """
        SELECT a.name, ma.role
        FROM manga_authors ma
        JOIN authors a ON a.id = ma.author_id
        WHERE ma.manga_id = ?
        ORDER BY ma.role
        """,
        (manga_id,),
    )
    author_rows = cursor.fetchall()
    assert len(author_rows) == 2
    roles = {r["role"] for r in author_rows}
    assert roles == {"artist", "author"}

    # Check genres
    cursor.execute(
        """
        SELECT g.name
        FROM manga_genres mg
        JOIN genres g ON g.id = mg.genre_id
        WHERE mg.manga_id = ?
        ORDER BY g.name ASC
        """,
        (manga_id,),
    )
    genre_rows = cursor.fetchall()
    assert [g["name"] for g in genre_rows] == ["Боевик", "Сверхъестественное"]


def test_upsert_provider_manga_idempotency_no_duplicates(catalog_db: sqlite3.Connection):
    """
    Repeated upsert of the same external item must NOT create duplicate records
    in manga, manga_sources, authors, or genres.
    """
    service = CatalogService(conn=catalog_db)

    item = ProviderMangaItem(
        provider_id="mangadex",
        provider_manga_id="md-102",
        title="Магическая Битва",
        alt_titles=["Jujutsu Kaisen"],
        description="Первоначальное описание",
        cover_url="https://example.com/jjk_old.jpg",
        status="ongoing",
        release_year=2018,
        authors=["Gege Akutami"],
        artists=["Gege Akutami"],
        genres=["Сёнэн", "Мистика"],
        available_languages=["ru"],
        source_url="https://mangadex.org/title/md-102",
    )

    id_first = service.upsert_provider_manga(item)
    id_second = service.upsert_provider_manga(item)

    assert id_first == id_second

    cursor = catalog_db.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM manga")
    assert cursor.fetchone()["cnt"] == 1

    cursor.execute("SELECT COUNT(*) as cnt FROM manga_sources")
    assert cursor.fetchone()["cnt"] == 1

    cursor.execute("SELECT COUNT(*) as cnt FROM authors")
    assert cursor.fetchone()["cnt"] == 1

    cursor.execute("SELECT COUNT(*) as cnt FROM genres")
    assert cursor.fetchone()["cnt"] == 2


def test_separate_works_with_same_title_do_not_auto_merge(catalog_db: sqlite3.Connection):
    """
    Per Team Lead directive: works with same title but different external IDs
    are NOT merged automatically; each gets a distinct canonical record and slug.
    """
    service = CatalogService(conn=catalog_db)

    item1 = ProviderMangaItem(
        provider_id="mangadex",
        provider_manga_id="md-one-shot",
        title="Одинокий Странник",
        description="Ваншот версия",
        status="completed",
        available_languages=["ru"],
    )
    item2 = ProviderMangaItem(
        provider_id="mangadex",
        provider_manga_id="md-serialized",
        title="Одинокий Странник",
        description="Сериализация",
        status="ongoing",
        available_languages=["ru"],
    )

    id1 = service.upsert_provider_manga(item1)
    id2 = service.upsert_provider_manga(item2)

    assert id1 != id2

    cursor = catalog_db.cursor()
    cursor.execute("SELECT id, slug FROM manga WHERE id IN (?, ?)", (id1, id2))
    rows = cursor.fetchall()
    slugs = {r["slug"] for r in rows}
    assert len(slugs) == 2
    assert "odinokiy-strannik" in slugs
    assert "odinokiy-strannik-2" in slugs


# ==============================================================================
# 2. Search & Integration with ProviderRegistry
# ==============================================================================

@pytest.mark.anyio
async def test_catalog_search_calls_mangadex_and_stores_results(catalog_db: sqlite3.Connection):
    """Catalog search fetches Russian titles from provider and registers them in catalog."""
    mock_provider = DummyMockProvider(provider_id="mangadex")
    mock_provider.search_mock.return_value = ProviderSearchResult(
        provider_id="mangadex",
        items=[
            ProviderMangaItem(
                provider_id="mangadex",
                provider_manga_id="md-201",
                title="Берсерк",
                alt_titles=["Berserk"],
                description="История Гатса.",
                cover_url="https://example.com/berserk.jpg",
                status="ongoing",
                release_year=1989,
                authors=["Kentaro Miura"],
                artists=["Kentaro Miura"],
                genres=["Темное фэнтези", "Сэйнэн"],
                available_languages=["ru"],
                source_url="https://mangadex.org/title/md-201",
            )
        ],
        total=1,
        page=1,
        limit=20,
        has_next=False,
    )

    registry = ProviderRegistry()
    registry.register(mock_provider)

    service = CatalogService(conn=catalog_db, registry=registry)
    results = await service.search(query="Берсерк", page=1, limit=20)

    # Provider should have been queried with Russian language filter
    mock_provider.search_mock.assert_awaited_once_with("Берсерк", 1, 20, ["ru"])

    assert len(results) == 1
    manga = results[0]
    assert manga.title == "Берсерк"
    assert manga.slug == "berserk"
    assert manga.release_year == 1989
    author_names = {a.name for a in manga.authors}
    assert author_names == {"Kentaro Miura"}
    author_roles = {a.role for a in manga.authors}
    assert author_roles == {"author", "artist"}
    assert len(manga.genres) == 2
    genre_names = {g.name for g in manga.genres}
    assert "Темное фэнтези" in genre_names

    # Verify no external source details are leaked in MangaListRead
    assert not hasattr(manga, "source_name")
    assert not hasattr(manga, "provider_manga_id")


@pytest.mark.anyio
async def test_catalog_search_graceful_fallback_on_network_error(catalog_db: sqlite3.Connection):
    """If provider fails with network error, service falls back to local DB without crashing."""
    # Pre-populate local DB
    service = CatalogService(conn=catalog_db)
    service.upsert_provider_manga(
        ProviderMangaItem(
            provider_id="mangadex",
            provider_manga_id="md-local-1",
            title="Токийский Гуль",
            description="Канеки Кен и гули.",
            available_languages=["ru"],
        )
    )

    # Mock provider that fails with ProviderNetworkError
    mock_provider = DummyMockProvider(provider_id="mangadex")
    mock_provider.search_mock.side_effect = ProviderNetworkError("MangaDex API unreachable")

    registry = ProviderRegistry()
    registry.register(mock_provider)

    service_with_provider = CatalogService(conn=catalog_db, registry=registry)
    results = await service_with_provider.search(query="Гуль", page=1, limit=20)

    # Should not raise exception, but return locally indexed result
    assert len(results) >= 1
    assert results[0].title == "Токийский Гуль"


@pytest.mark.anyio
async def test_catalog_search_graceful_fallback_on_rate_limit(catalog_db: sqlite3.Connection):
    """If provider returns rate limit error, search degrades gracefully."""
    mock_provider = DummyMockProvider(provider_id="mangadex")
    mock_provider.search_mock.side_effect = ProviderRateLimitError("Rate limit exceeded", retry_after=5)

    registry = ProviderRegistry()
    registry.register(mock_provider)

    service = CatalogService(conn=catalog_db, registry=registry)
    results = await service.search(query="Несуществующий", page=1, limit=20)
    assert results == []


# ==============================================================================
# 3. Manga Detail View Tests
# ==============================================================================

@pytest.mark.anyio
async def test_get_manga_by_id_and_slug(catalog_db: sqlite3.Connection):
    """Ensure manga detail retrieval works by numeric ID and string slug."""
    service = CatalogService(conn=catalog_db)

    manga_id = service.upsert_provider_manga(
        ProviderMangaItem(
            provider_id="mangadex",
            provider_manga_id="md-detail-test",
            title="Стальной Алхимик",
            alt_titles=["Fullmetal Alchemist"],
            description="Братья Элрики и философский камень.",
            cover_url="https://example.com/fma.jpg",
            status="completed",
            release_year=2001,
            authors=["Hiromu Arakawa"],
            genres=["Сёнэн", "Приключения"],
            available_languages=["ru"],
        )
    )

    # 1. Fetch by numeric ID
    detail_by_id = await service.get_manga_by_id_or_slug(str(manga_id))
    assert detail_by_id is not None
    assert detail_by_id.id == manga_id
    assert detail_by_id.title == "Стальной Алхимик"
    assert detail_by_id.views_count == 1
    assert detail_by_id.sources == []  # External sources are stripped

    # 2. Fetch by slug
    detail_by_slug = await service.get_manga_by_id_or_slug("stalnoy-alkhimik")
    assert detail_by_slug is not None
    assert detail_by_slug.id == manga_id
    assert detail_by_slug.views_count == 2  # Incremented views

    # 3. Fetch non-existent
    assert await service.get_manga_by_id_or_slug("non-existent-manga") is None


# ==============================================================================
# 4. HTTP API Endpoint Tests via TestClient
# ==============================================================================

def test_api_manga_search_endpoint():
    """Verify GET /api/manga/search endpoint behavior."""
    with TestClient(app) as client:
        # Override ProviderRegistry with mock for predictable testing
        mock_provider = DummyMockProvider(provider_id="mangadex")
        mock_provider.search_mock.return_value = ProviderSearchResult(
            provider_id="mangadex",
            items=[
                ProviderMangaItem(
                    provider_id="mangadex",
                    provider_manga_id="md-api-01",
                    title="Атака Титанов",
                    alt_titles=["Attack on Titan"],
                    description="Стены защищают человечество от титанов.",
                    cover_url="https://example.com/aot.jpg",
                    status="completed",
                    release_year=2009,
                    authors=["Hajime Isayama"],
                    genres=["Сёнэн", "Драма"],
                    available_languages=["ru"],
                )
            ],
            total=1,
            page=1,
            limit=20,
            has_next=False,
        )

        app.state.provider_registry = ProviderRegistry()
        app.state.provider_registry.register(mock_provider)

        resp = client.get("/api/manga/search", params={"q": "Титанов"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        first_item = data[0]
        assert first_item["title"] == "Атака Титанов"
        assert first_item["slug"] == "ataka-titanov"
        assert "genres" in first_item
        assert "authors" in first_item

        # Details endpoint test
        slug = first_item["slug"]
        detail_resp = client.get(f"/api/manga/{slug}")
        assert detail_resp.status_code == 200
        detail_data = detail_resp.json()
        assert detail_data["title"] == "Атака Титанов"
        assert detail_data["description"] == "Стены защищают человечество от титанов."
        assert detail_data["sources"] == []


def test_api_manga_detail_not_found():
    """Verify GET /api/manga/{id_or_slug} returns 404 when title does not exist."""
    with TestClient(app) as client:
        resp = client.get("/api/manga/definitely-not-found-slug-99999")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Manga not found"


def test_api_manga_cover_proxy_disallowed_host():
    """Verify GET /api/manga/cover/proxy rejects non-whitelisted hosts with HTTP 400."""
    with TestClient(app) as client:
        resp = client.get("/api/manga/cover/proxy", params={"url": "https://evil.com/malicious.jpg"})
        assert resp.status_code == 400
        assert "not permitted" in resp.json()["detail"]


def test_api_manga_cover_proxy_success(monkeypatch):
    """Verify GET /api/manga/cover/proxy successfully proxies valid MangaDex covers."""
    class MockResponse:
        status_code = 200
        content = b"fake-jpeg-bytes"
        headers = {"content-type": "image/jpeg"}

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, headers=None):
            return MockResponse()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    with TestClient(app) as client:
        valid_url = "https://uploads.mangadex.org/covers/dummy/cover.jpg.512.jpg"
        resp = client.get("/api/manga/cover/proxy", params={"url": valid_url})
        assert resp.status_code == 200
        assert resp.content == b"fake-jpeg-bytes"
        assert resp.headers["content-type"] == "image/jpeg"
        assert "max-age" in resp.headers["cache-control"]


# ==============================================================================
# 5. Russian Chapter Synchronization, Deduplication & Endpoints (TASK 011.1)
# ==============================================================================

@pytest.mark.anyio
async def test_sync_chapters_pagination_and_deduplication(catalog_db: sqlite3.Connection):
    """
    Verify sync_manga_chapters paginates through all pages, accurately saves
    chapters into SQLite, and is 100% idempotent on repeated executions (no duplicates).
    """
    mock_provider = DummyMockProvider(provider_id="mangadex")

    # Page 1: Chapters 1 (Scan A), 1 (Scan B - same chapter number, different UUID), 2
    page1 = ProviderChaptersResult(
        provider_id="mangadex",
        provider_manga_id="md-berserk-test",
        chapters=[
            ProviderChapterItem(
                provider_id="mangadex",
                provider_manga_id="md-berserk-test",
                provider_chapter_id="ch-uuid-1-a",
                chapter_number_raw="1",
                chapter_number_numeric=1.0,
                is_special=False,
                volume_number=1,
                title="Chapter 1 Team A",
                language="ru",
                scanlation_group="Team A",
            ),
            ProviderChapterItem(
                provider_id="mangadex",
                provider_manga_id="md-berserk-test",
                provider_chapter_id="ch-uuid-1-b",
                chapter_number_raw="1",
                chapter_number_numeric=1.0,
                is_special=False,
                volume_number=1,
                title="Chapter 1 Team B",
                language="ru",
                scanlation_group="Team B",
            ),
            ProviderChapterItem(
                provider_id="mangadex",
                provider_manga_id="md-berserk-test",
                provider_chapter_id="ch-uuid-2",
                chapter_number_raw="2",
                chapter_number_numeric=2.0,
                is_special=False,
                volume_number=1,
                title="Chapter 2",
                language="ru",
                scanlation_group="Team A",
            ),
        ],
        total=4,
        page=1,
        limit=3,
        has_next=True,
    )

    # Page 2: Chapter 3
    page2 = ProviderChaptersResult(
        provider_id="mangadex",
        provider_manga_id="md-berserk-test",
        chapters=[
            ProviderChapterItem(
                provider_id="mangadex",
                provider_manga_id="md-berserk-test",
                provider_chapter_id="ch-uuid-3",
                chapter_number_raw="3",
                chapter_number_numeric=3.0,
                is_special=False,
                volume_number=1,
                title="Chapter 3",
                language="ru",
                scanlation_group="Team A",
            ),
        ],
        total=4,
        page=2,
        limit=3,
        has_next=False,
    )

    async def mock_get_chapters(manga_id, language, page, limit):
        if page == 1:
            return page1
        return page2

    mock_provider.get_chapters_mock.side_effect = mock_get_chapters

    registry = ProviderRegistry()
    registry.register(mock_provider)

    service = CatalogService(conn=catalog_db, registry=registry)

    # Create manga and source
    manga_id = service.upsert_provider_manga(
        ProviderMangaItem(
            provider_id="mangadex",
            provider_manga_id="md-berserk-test",
            title="Berserk Test",
            alt_titles=[],
            status="ongoing",
            authors=["Kentaro Miura"],
            genres=["Dark Fantasy"],
            available_languages=["ru"],
        )
    )

    # 1. First sync: should insert 4 chapters across 2 pages
    chapters_after_first = await service.sync_manga_chapters(manga_id)
    assert len(chapters_after_first) == 4

    cursor = catalog_db.cursor()
    cursor.execute("SELECT COUNT(*) FROM chapters WHERE manga_id = ?", (manga_id,))
    assert cursor.fetchone()[0] == 4

    # 2. Second sync: must not create duplicates
    chapters_after_second = await service.sync_manga_chapters(manga_id)
    assert len(chapters_after_second) == 4

    cursor.execute("SELECT COUNT(*) FROM chapters WHERE manga_id = ?", (manga_id,))
    assert cursor.fetchone()[0] == 4


@pytest.mark.anyio
async def test_russian_only_enforcement_in_sync(catalog_db: sqlite3.Connection):
    """Ensure non-Russian chapters returned by any provider are ignored during DB insertion."""
    mock_provider = DummyMockProvider(provider_id="mangadex")

    mock_provider.get_chapters_mock.return_value = ProviderChaptersResult(
        provider_id="mangadex",
        provider_manga_id="md-lang-test",
        chapters=[
            ProviderChapterItem(
                provider_id="mangadex",
                provider_manga_id="md-lang-test",
                provider_chapter_id="ch-ru",
                chapter_number_numeric=1.0,
                language="ru",
                title="Russian",
            ),
            ProviderChapterItem(
                provider_id="mangadex",
                provider_manga_id="md-lang-test",
                provider_chapter_id="ch-en",
                chapter_number_numeric=1.0,
                language="en",
                title="English Sneak",
            ),
        ],
        total=2,
        page=1,
        limit=10,
        has_next=False,
    )

    registry = ProviderRegistry()
    registry.register(mock_provider)
    service = CatalogService(conn=catalog_db, registry=registry)

    manga_id = service.upsert_provider_manga(
        ProviderMangaItem(
            provider_id="mangadex",
            provider_manga_id="md-lang-test",
            title="Lang Test",
            alt_titles=[],
            status="ongoing",
            available_languages=["ru"],
        )
    )

    synced = await service.sync_manga_chapters(manga_id)
    assert len(synced) == 1
    assert synced[0].source_chapter_id == "ch-ru"
    assert synced[0].language == "ru"


@pytest.mark.anyio
async def test_get_manga_by_external_uuid(catalog_db: sqlite3.Connection):
    """Verify that get_manga_by_id_or_slug can resolve directly by MangaDex UUID."""
    mock_provider = DummyMockProvider(provider_id="mangadex")
    mock_provider.get_details_mock.return_value = ProviderMangaItem(
        provider_id="mangadex",
        provider_manga_id="801513ba-a712-498c-8f57-cae55b38cc92",
        title="Berserk External",
        alt_titles=["ベルセルク"],
        description="Guts story",
        status="ongoing",
        authors=["Kentaro Miura"],
        genres=["Dark Fantasy"],
        available_languages=["ru"],
    )
    mock_provider.get_chapters_mock.return_value = ProviderChaptersResult(
        provider_id="mangadex",
        provider_manga_id="801513ba-a712-498c-8f57-cae55b38cc92",
        chapters=[],
        total=0,
        page=1,
        limit=100,
        has_next=False,
    )

    registry = ProviderRegistry()
    registry.register(mock_provider)
    service = CatalogService(conn=catalog_db, registry=registry)

    # Not in DB yet, query directly by UUID
    manga = await service.get_manga_by_id_or_slug("801513ba-a712-498c-8f57-cae55b38cc92")
    assert manga is not None
    assert manga.title == "Berserk External"
    assert manga.sources == []  # Not exposed


def test_api_manga_chapters_list_and_sync_endpoints():
    """Verify GET /api/manga/{id}/chapters and POST /api/manga/{id}/sync endpoints."""
    mock_provider = DummyMockProvider(provider_id="mangadex")
    mock_provider.get_details_mock.return_value = ProviderMangaItem(
        provider_id="mangadex",
        provider_manga_id="md-ep-test",
        title="Endpoint Test",
        alt_titles=[],
        status="ongoing",
        available_languages=["ru"],
    )
    mock_provider.get_chapters_mock.return_value = ProviderChaptersResult(
        provider_id="mangadex",
        provider_manga_id="md-ep-test",
        chapters=[
            ProviderChapterItem(
                provider_id="mangadex",
                provider_manga_id="md-ep-test",
                provider_chapter_id="ep-ch-1",
                chapter_number_numeric=1.0,
                language="ru",
                title="Ch 1",
            ),
            ProviderChapterItem(
                provider_id="mangadex",
                provider_manga_id="md-ep-test",
                provider_chapter_id="ep-ch-2",
                chapter_number_numeric=2.0,
                language="ru",
                title="Ch 2",
            ),
        ],
        total=2,
        page=1,
        limit=100,
        has_next=False,
    )

    mock_registry = ProviderRegistry()
    mock_registry.register(mock_provider)

    with TestClient(app) as client:
        app.state.provider_registry = mock_registry
        # 1. Fetch by UUID: triggers auto-provision and sync
        detail_resp = client.get("/api/manga/md-ep-test")
        assert detail_resp.status_code == 200
        detail_data = detail_resp.json()
        assert detail_data["title"] == "Endpoint Test"
        assert len(detail_data["chapters"]) == 2

        # 2. GET /api/manga/{id}/chapters?order=desc
        manga_id = detail_data["id"]
        ch_resp = client.get(f"/api/manga/{manga_id}/chapters", params={"order": "desc"})
        assert ch_resp.status_code == 200
        chapters = ch_resp.json()
        assert len(chapters) == 2
        assert chapters[0]["chapter_number"] == 2.0
        assert chapters[1]["chapter_number"] == 1.0

        # 3. POST /api/manga/{id}/sync
        sync_resp = client.post(f"/api/manga/{manga_id}/sync")
        assert sync_resp.status_code == 200
        sync_data = sync_resp.json()
        assert sync_data["status"] == "ok"
        assert sync_data["chapters_count"] == 2
