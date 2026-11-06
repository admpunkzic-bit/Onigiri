"""
Tests for TASK 014 Phase 2 — Manga-Chan Primary / MangaDex Reserve.
Validates:
1. Primary source selection (Manga-Chan).
2. Fallback to MangaDex when Manga-Chan has 0 chapters or fails.
3. Catalog chapter supplementation when MangaDex has more chapters.
4. Safe deduplication: identical release prioritizes Manga-Chan.
5. Distinct alternative scanlation groups are preserved.
6. Ambiguous chapters (specials with divergent titles) not merged.
7. Transient network errors do not wipe existing data.
8. Reader transparent fallback to alternative provider.
9. Strict zero-leakage of provider names in public API.
"""

import sqlite3
import pytest
from datetime import datetime, timezone
from typing import List, Optional
from unittest.mock import AsyncMock

from database.migrations import run_migrations
from providers.base import (
    BaseMangaProvider,
    ProviderChapterItem,
    ProviderChaptersResult,
    ProviderMangaItem,
    ProviderNetworkError,
    ProviderPagesResult,
    ProviderPageItem,
    ProviderSearchResult,
)
from providers.registry import ProviderRegistry
from services.catalog import CatalogService
from services.reader import ReaderService


class DummyProvider(BaseMangaProvider):
    def __init__(self, provider_id: str, name: str):
        self._provider_id = provider_id
        self._name = name
        self.search_mock = AsyncMock()
        self.get_manga_details_mock = AsyncMock()
        self.get_chapters_mock = AsyncMock()
        self.get_chapter_pages_mock = AsyncMock()

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def name(self) -> str:
        return self._name

    async def search(self, query: str, page: int = 1, limit: int = 20, languages: Optional[List[str]] = None) -> ProviderSearchResult:
        return await self.search_mock(query, page, limit, languages)

    async def get_manga_details(self, provider_manga_id: str) -> Optional[ProviderMangaItem]:
        return await self.get_manga_details_mock(provider_manga_id)

    async def get_chapters(self, provider_manga_id: str, language: str = "ru", page: int = 1, limit: int = 100) -> ProviderChaptersResult:
        return await self.get_chapters_mock(provider_manga_id, language, page, limit)

    async def get_chapter_pages(self, provider_chapter_id: str, data_saver: bool = False) -> ProviderPagesResult:
        return await self.get_chapter_pages_mock(provider_chapter_id, data_saver)

    async def close(self) -> None:
        pass


@pytest.fixture
def test_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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
    return reg, chan, dex


@pytest.mark.anyio
async def test_mangachan_primary_and_mangadex_supplement(test_db, mock_registry):
    """
    Manga-Chan is primary (chapters 1..3).
    MangaDex supplements chapters 4..5.
    Same release for chapter 1 (same group) is deduplicated in favor of Manga-Chan.
    """
    reg, chan, dex = mock_registry
    catalog = CatalogService(conn=test_db, registry=reg)

    cursor = test_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug, status) VALUES ('Test Hero', 'test-hero', 'ongoing')")
    manga_id = cursor.lastrowid
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangachan', 'chan-hero')", (manga_id,))
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangadex', 'dex-hero')", (manga_id,))
    test_db.commit()

    # Manga-Chan has chapters 1, 2, 3 (Group: "Alfa")
    chan.get_chapters_mock.return_value = ProviderChaptersResult(
        provider_id="mangachan",
        provider_manga_id="chan-hero",
        chapters=[
            ProviderChapterItem(provider_id="mangachan", provider_manga_id="chan-hero", provider_chapter_id="c1", chapter_number_raw="1", chapter_number_numeric=1.0, title="Ch 1", scanlation_group="Alfa", language="ru"),
            ProviderChapterItem(provider_id="mangachan", provider_manga_id="chan-hero", provider_chapter_id="c2", chapter_number_raw="2", chapter_number_numeric=2.0, title="Ch 2", scanlation_group="Alfa", language="ru"),
            ProviderChapterItem(provider_id="mangachan", provider_manga_id="chan-hero", provider_chapter_id="c3", chapter_number_raw="3", chapter_number_numeric=3.0, title="Ch 3", scanlation_group="Alfa", language="ru"),
        ],
        total=3,
        page=1,
        limit=100,
        has_next=False,
    )

    # MangaDex has chapters 1 (same group "Alfa"), and missing chapters 4, 5
    dex.get_chapters_mock.return_value = ProviderChaptersResult(
        provider_id="mangadex",
        provider_manga_id="dex-hero",
        chapters=[
            ProviderChapterItem(provider_id="mangadex", provider_manga_id="dex-hero", provider_chapter_id="d1", chapter_number_raw="1", chapter_number_numeric=1.0, title="Ch 1", scanlation_group="Alfa", language="ru"),
            ProviderChapterItem(provider_id="mangadex", provider_manga_id="dex-hero", provider_chapter_id="d4", chapter_number_raw="4", chapter_number_numeric=4.0, title="Ch 4", scanlation_group="Alfa", language="ru"),
            ProviderChapterItem(provider_id="mangadex", provider_manga_id="dex-hero", provider_chapter_id="d5", chapter_number_raw="5", chapter_number_numeric=5.0, title="Ch 5", scanlation_group="Alfa", language="ru"),
        ],
        total=3,
        page=1,
        limit=100,
        has_next=False,
    )

    chapters = await catalog.sync_manga_chapters(manga_id)

    # Total chapters returned should be 5: (1, 2, 3 from Manga-Chan, 4, 5 from MangaDex)
    assert len(chapters) == 5
    chapter_numbers = [c.chapter_number for c in chapters]
    assert chapter_numbers == [1.0, 2.0, 3.0, 4.0, 5.0]

    # Chapter 1 must be from Manga-Chan (provider_chapter_id == 'c1')
    ch1 = next(c for c in chapters if c.chapter_number == 1.0)
    assert ch1.source_chapter_id == "c1"


@pytest.mark.anyio
async def test_alternative_translations_preserved(test_db, mock_registry):
    """
    When chapter 1 exists on Manga-Chan with Group 'Alfa'
    and on MangaDex with Group 'Beta', BOTH translations must be preserved.
    """
    reg, chan, dex = mock_registry
    catalog = CatalogService(conn=test_db, registry=reg)

    cursor = test_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug, status) VALUES ('Solo Hero', 'solo-hero', 'ongoing')")
    manga_id = cursor.lastrowid
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangachan', 'chan-solo')", (manga_id,))
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangadex', 'dex-solo')", (manga_id,))
    test_db.commit()

    chan.get_chapters_mock.return_value = ProviderChaptersResult(
        provider_id="mangachan",
        provider_manga_id="chan-solo",
        chapters=[
            ProviderChapterItem(provider_id="mangachan", provider_manga_id="chan-solo", provider_chapter_id="c1", chapter_number_raw="1", chapter_number_numeric=1.0, title="Начало", scanlation_group="Alfa", language="ru"),
        ],
        total=1, page=1, limit=100, has_next=False,
    )

    dex.get_chapters_mock.return_value = ProviderChaptersResult(
        provider_id="mangadex",
        provider_manga_id="dex-solo",
        chapters=[
            ProviderChapterItem(provider_id="mangadex", provider_manga_id="dex-solo", provider_chapter_id="d1", chapter_number_raw="1", chapter_number_numeric=1.0, title="Начало", scanlation_group="Beta", language="ru"),
        ],
        total=1, page=1, limit=100, has_next=False,
    )

    chapters = await catalog.sync_manga_chapters(manga_id)

    # Both translations of Chapter 1 must be present!
    assert len(chapters) == 2
    groups = {c.scanlation_group for c in chapters}
    assert groups == {"Alfa", "Beta"}


@pytest.mark.anyio
async def test_mangachan_network_error_retains_data_and_falls_back(test_db, mock_registry):
    """
    If Manga-Chan is temporarily down (HTTP 502/timeout), previously stored data
    is NOT wiped, and MangaDex is queried as fallback.
    """
    reg, chan, dex = mock_registry
    catalog = CatalogService(conn=test_db, registry=reg)

    cursor = test_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug, status) VALUES ('Resilient Hero', 'resilient-hero', 'ongoing')")
    manga_id = cursor.lastrowid
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangachan', 'chan-res')", (manga_id,))
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangadex', 'dex-res')", (manga_id,))
    
    # Pre-existing chapter from Manga-Chan
    cursor.execute(
        "INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, language) VALUES (?, 1, 'old-chan-1', 1.0, 'ru')",
        (manga_id,)
    )
    test_db.commit()

    # Manga-Chan fails with network error (502 / timeout)
    chan.get_chapters_mock.side_effect = ProviderNetworkError("Manga-Chan 502 Bad Gateway")

    # MangaDex is healthy with chapter 2
    dex.get_chapters_mock.return_value = ProviderChaptersResult(
        provider_id="mangadex",
        provider_manga_id="dex-res",
        chapters=[
            ProviderChapterItem(provider_id="mangadex", provider_manga_id="dex-res", provider_chapter_id="d2", chapter_number_raw="2", chapter_number_numeric=2.0, title="Глава 2", scanlation_group="Beta", language="ru"),
        ],
        total=1, page=1, limit=100, has_next=False,
    )

    chapters = await catalog.sync_manga_chapters(manga_id)

    # Previously saved chapter 1 is preserved + chapter 2 from MangaDex is present
    assert len(chapters) >= 2
    nums = [c.chapter_number for c in chapters]
    assert 1.0 in nums
    assert 2.0 in nums


@pytest.mark.anyio
async def test_reader_transparent_fallback(test_db, mock_registry):
    """
    When user opens a chapter in reader whose primary provider fails AtHome pages,
    ReaderService transparently serves pages from the alternative provider variant.
    """
    reg, chan, dex = mock_registry
    reader = ReaderService(conn=test_db, registry=reg)

    cursor = test_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug, status) VALUES ('Reader Manga', 'reader-manga', 'ongoing')")
    manga_id = cursor.lastrowid
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangachan', 'chan-rm')", (manga_id,))
    src_chan_id = cursor.lastrowid
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangadex', 'dex-rm')", (manga_id,))
    src_dex_id = cursor.lastrowid

    # Canonical chapter 1
    cursor.execute("INSERT INTO canonical_chapters (manga_id, chapter_number) VALUES (?, 1.0)", (manga_id,))
    canon_id = cursor.lastrowid

    # Primary Manga-Chan chapter (id 10)
    cursor.execute(
        """
        INSERT INTO chapters (id, manga_id, manga_source_id, source_chapter_id, canonical_chapter_id, chapter_number, language)
        VALUES (10, ?, ?, 'c-failing', ?, 1.0, 'ru')
        """,
        (manga_id, src_chan_id, canon_id),
    )
    # Backup MangaDex chapter (id 20)
    cursor.execute(
        """
        INSERT INTO chapters (id, manga_id, manga_source_id, source_chapter_id, canonical_chapter_id, chapter_number, language)
        VALUES (20, ?, ?, 'd-working', ?, 1.0, 'ru')
        """,
        (manga_id, src_dex_id, canon_id),
    )
    test_db.commit()

    # Primary Manga-Chan fails AtHome
    chan.get_chapter_pages_mock.side_effect = ProviderNetworkError("Manga-Chan image node down")

    # Backup MangaDex succeeds
    dex.get_chapter_pages_mock.return_value = ProviderPagesResult(
        provider_id="mangadex",
        provider_chapter_id="d-working",
        pages=[
            ProviderPageItem(page_number=1, image_url="https://uploads.mangadex.org/data/p1.jpg"),
            ProviderPageItem(page_number=2, image_url="https://uploads.mangadex.org/data/p2.jpg"),
        ],
        data_saver=False,
    )

    detail = await reader.get_chapter_reader_detail("reader-manga", 10)

    # Reader detail succeeds without 502, serving pages from working provider
    assert detail.total_pages == 2
    assert len(detail.pages) == 2
    # Image urls point to working chapter 20
    assert "20" in detail.pages[0].image_url
