"""
Test suite for TASK 014.2:
- Manga-Chan and MangaDex chapter page streaming.
- MangaDex 404 recovery with AtHome dataSaver fallback.
- MangaDex toggle (enable_mangadex=False/True) behavior:
  - 0 outgoing requests to MangaDex when disabled.
  - MangaDex chapters excluded from search and chapter lists when disabled.
  - Reading MangaDex chapters yields 403 when disabled, or transparently falls back to Manga-Chan.
  - Re-enabling immediately restores access without database data loss.
  - API header 'X-Enable-MangaDex' and query parameter 'enable_mangadex' handling.
"""

import sqlite3
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.routes import get_db, get_registry
from database.connection import get_connection
from database.migrations import run_migrations
from main import app
from providers.base import (
    BaseMangaProvider,
    ProviderChapterItem,
    ProviderChaptersResult,
    ProviderMangaItem,
    ProviderPageItem,
    ProviderPagesResult,
    ProviderSearchResult,
)
from providers.registry import ProviderRegistry
from schemas.manga import ChapterReaderPageItem
from services.catalog import CatalogService
from services.reader import ReaderService


class DummyProvider(BaseMangaProvider):
    def __init__(self, provider_id: str, name: str):
        self._provider_id = provider_id
        self._name = name
        self.search_call_count = 0
        self.chapters_call_count = 0
        self.pages_call_count = 0

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def name(self) -> str:
        return self._name

    async def search(self, query: str, page: int = 1, limit: int = 20, languages: Optional[List[str]] = None) -> ProviderSearchResult:
        self.search_call_count += 1
        return ProviderSearchResult(
            provider_id=self._provider_id,
            items=[
                ProviderMangaItem(
                    provider_id=self._provider_id,
                    provider_manga_id=f"{self._provider_id}-m1",
                    title="Test Manga",
                    source_url=f"https://{self._provider_id}.test/m1",
                    available_languages=["ru"],
                )
            ],
            total=1,
            page=page,
            limit=limit,
            has_next=False,
        )

    async def get_manga_details(self, provider_manga_id: str) -> Optional[ProviderMangaItem]:
        return ProviderMangaItem(
            provider_id=self._provider_id,
            provider_manga_id=provider_manga_id,
            title="Test Manga",
            source_url=f"https://{self._provider_id}.test/{provider_manga_id}",
            available_languages=["ru"],
        )

    async def get_chapters(self, provider_manga_id: str, language: str = "ru", page: int = 1, limit: int = 100) -> ProviderChaptersResult:
        self.chapters_call_count += 1
        return ProviderChaptersResult(
            provider_id=self._provider_id,
            provider_manga_id=provider_manga_id,
            chapters=[
                ProviderChapterItem(
                    provider_chapter_id=f"{self._provider_id}-ch1",
                    chapter_number="1",
                    chapter_number_numeric=1.0,
                    volume_number="1",
                    title=f"Chapter 1 from {self._name}",
                    language="ru",
                    scanlation_group=f"{self._name} Team",
                ),
                ProviderChapterItem(
                    provider_chapter_id=f"{self._provider_id}-ch2",
                    chapter_number="2",
                    chapter_number_numeric=2.0,
                    volume_number="1",
                    title=f"Chapter 2 from {self._name}",
                    language="ru",
                    scanlation_group=f"{self._name} Team",
                ),
            ],
            total=2,
            page=page,
            limit=limit,
            has_next=False,
        )

    async def get_chapter_pages(self, provider_chapter_id: str, data_saver: bool = False) -> ProviderPagesResult:
        self.pages_call_count += 1
        return ProviderPagesResult(
            provider_id=self._provider_id,
            provider_chapter_id=provider_chapter_id,
            pages=[
                ProviderPageItem(page_number=1, image_url=f"https://{self._provider_id}.cdn.test/{provider_chapter_id}/1.jpg"),
                ProviderPageItem(page_number=2, image_url=f"https://{self._provider_id}.cdn.test/{provider_chapter_id}/2.jpg"),
            ]
        )

    async def close(self) -> None:
        pass


@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_toggle.db"
    conn = get_connection(db_file)
    run_migrations(conn)
    yield conn
    conn.close()


@pytest.fixture
def mock_registry():
    reg = ProviderRegistry()
    chan = DummyProvider("mangachan", "Manga-Chan")
    dex = DummyProvider("mangadex", "MangaDex")
    reg.register(chan)
    reg.register(dex)
    return reg


@pytest.mark.anyio
async def test_search_respects_enable_mangadex(test_db, mock_registry):
    catalog = CatalogService(conn=test_db, registry=mock_registry)
    dex_prov: DummyProvider = mock_registry.get("mangadex")
    chan_prov: DummyProvider = mock_registry.get("mangachan")

    # 1. With enable_mangadex=True: both should be queried
    await catalog.search(query="Solo", enable_mangadex=True)
    assert chan_prov.search_call_count == 1
    assert dex_prov.search_call_count == 1

    # 2. With enable_mangadex=False: MangaDex must NOT be queried at all (0 calls)
    chan_prov.search_call_count = 0
    dex_prov.search_call_count = 0
    await catalog.search(query="Solo Leveling", enable_mangadex=False)
    assert chan_prov.search_call_count == 1
    assert dex_prov.search_call_count == 0  # 0 outbound requests to MangaDex


@pytest.mark.anyio
async def test_sync_and_load_chapters_respects_enable_mangadex(test_db, mock_registry):
    catalog = CatalogService(conn=test_db, registry=mock_registry)
    dex_prov: DummyProvider = mock_registry.get("mangadex")
    chan_prov: DummyProvider = mock_registry.get("mangachan")

    # Insert a canonical manga
    cursor = test_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Test Manga', 'test-manga')")
    manga_id = cursor.lastrowid
    test_db.commit()

    # Sync with enable_mangadex=True
    chapters = await catalog.sync_manga_chapters(manga_id, enable_mangadex=True)
    assert dex_prov.chapters_call_count > 0

    # Load chapters with enable_mangadex=False: MangaDex chapters must be excluded
    chapters_no_dex = catalog._load_manga_chapters(manga_id, enable_mangadex=False)
    for ch in chapters_no_dex:
        # Check that no MangaDex chapters are present
        cursor.execute("SELECT ms.source_name FROM chapters c JOIN manga_sources ms ON ms.id = c.manga_source_id WHERE c.id = ?", (ch.id,))
        row = cursor.fetchone()
        assert row["source_name"] != "mangadex"

    # Re-enable: MangaDex chapters are immediately accessible again without data loss
    chapters_with_dex = catalog._load_manga_chapters(manga_id, enable_mangadex=True)
    assert len(chapters_with_dex) >= len(chapters_no_dex)


@pytest.mark.anyio
async def test_reader_service_respects_enable_mangadex(test_db, mock_registry):
    cursor = test_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Manga X', 'manga-x')")
    manga_id = cursor.lastrowid

    # Add MangaDex source & chapter
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangadex', 'dex-1')", (manga_id,))
    dex_src_id = cursor.lastrowid
    cursor.execute(
        "INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, language) VALUES (?, ?, 'dex-ch-10', 10, 'ru')",
        (manga_id, dex_src_id),
    )
    dex_ch_id = cursor.lastrowid
    test_db.commit()

    reader = ReaderService(conn=test_db, registry=mock_registry)

    # When enable_mangadex=False and only MangaDex source exists: must raise 403 Forbidden
    with pytest.raises(HTTPException) as exc_info:
        await reader.get_chapter_reader_detail("manga-x", dex_ch_id, enable_mangadex=False)
    assert exc_info.value.status_code == 403
    assert "MangaDex отключён" in exc_info.value.detail

    with pytest.raises(HTTPException) as exc_info2:
        await reader.get_page_image_stream(dex_ch_id, 1, enable_mangadex=False)
    assert exc_info2.value.status_code == 403
    assert "MangaDex отключён" in exc_info2.value.detail


@pytest.mark.anyio
async def test_mangadex_datasaver_recovery_on_404(test_db, mock_registry):
    """Verify that when MangaDex returns 404 on data/, ReaderService automatically falls back to dataSaver."""
    cursor = test_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Manga Dex Fallback', 'manga-dex-fb')")
    manga_id = cursor.lastrowid
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangadex', 'dex-fb-src')", (manga_id,))
    src_id = cursor.lastrowid
    cursor.execute(
        "INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, language) VALUES (?, ?, 'dex-ch-fb', 1, 'ru')",
        (manga_id, src_id),
    )
    ch_id = cursor.lastrowid
    test_db.commit()

    reader = ReaderService(conn=test_db, registry=mock_registry)

    # Mock get_athome_pages to return distinct URLs for full and dataSaver
    async def mock_get_athome(source_ch_id, data_saver=False, force_refresh=False, provider_id="mangadex"):
        if data_saver:
            return ProviderPagesResult(
                provider_id="mangadex",
                provider_chapter_id=source_ch_id,
                pages=[ProviderPageItem(page_number=1, image_url="https://uploads.mangadex.org/data-saver/p1.jpg")]
            )
        return ProviderPagesResult(
            provider_id="mangadex",
            provider_chapter_id=source_ch_id,
            pages=[ProviderPageItem(page_number=1, image_url="https://uploads.mangadex.org/data/p1.png")]
        )

    reader.get_athome_pages = mock_get_athome

    # Mock httpx responses: 404 for /data/, 200 with JPEG for /data-saver/
    jpeg_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"

    async def mock_client_get(self, url, *args, **kwargs):
        if "data-saver" in str(url):
            return httpx.Response(200, content=jpeg_bytes, headers={"Content-Type": "image/jpeg"})
        return httpx.Response(404, content=b"Not found")

    with patch.object(httpx.AsyncClient, "get", mock_client_get):
        img_bytes, ctype = await reader.get_page_image_stream(ch_id, 1, data_saver=False, enable_mangadex=True)
        assert img_bytes == jpeg_bytes
        assert ctype == "image/jpeg"


def test_api_routes_respect_header_and_query(test_db, mock_registry):
    app.dependency_overrides[get_db] = lambda: test_db
    app.dependency_overrides[get_registry] = lambda: mock_registry
    client = TestClient(app)

    try:
        # Search with header X-Enable-MangaDex: 0
        dex_prov: DummyProvider = mock_registry.get("mangadex")
        dex_prov.search_call_count = 0

        res = client.get("/api/manga/search?q=Hunter", headers={"X-Enable-MangaDex": "0"})
        assert res.status_code == 200
        assert dex_prov.search_call_count == 0

        # Search with query ?enable_mangadex=false
        res2 = client.get("/api/manga/search?q=Hunter&enable_mangadex=false")
        assert res2.status_code == 200
        assert dex_prov.search_call_count == 0

        # Search with enabled (default)
        res3 = client.get("/api/manga/search?q=Hunter")
        assert res3.status_code == 200
        assert dex_prov.search_call_count > 0
    finally:
        app.dependency_overrides.clear()
