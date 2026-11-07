import pytest
import sqlite3
from typing import List, Optional

from database.migrations import run_migrations
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
from services.catalog import CatalogService
from services.reader import ReaderService


@pytest.fixture
def test_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    yield conn
    conn.close()


class MockTestProvider(BaseMangaProvider):
    def __init__(self, provider_id: str, name: str):
        self._provider_id = provider_id
        self._name = name
        self.search_results: List[ProviderMangaItem] = []
        self.chapters_results: List[ProviderChapterItem] = []
        self.pages_results: List[str] = []
        self.should_fail_pages = False

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def name(self) -> str:
        return self._name

    async def search(self, query: str, page: int = 1, limit: int = 20, languages: Optional[List[str]] = None) -> ProviderSearchResult:
        return ProviderSearchResult(
            provider_id=self.provider_id,
            items=self.search_results,
            total=len(self.search_results),
            page=page,
            limit=limit,
            has_next=False,
        )

    async def get_manga_details(self, provider_manga_id: str) -> Optional[ProviderMangaItem]:
        for it in self.search_results:
            if it.provider_manga_id == provider_manga_id:
                return it
        return None

    async def get_chapters(self, provider_manga_id: str, language: Optional[str] = None, page: int = 1, limit: int = 100) -> ProviderChaptersResult:
        return ProviderChaptersResult(
            provider_id=self.provider_id,
            provider_manga_id=provider_manga_id,
            chapters=self.chapters_results,
            total=len(self.chapters_results),
            page=page,
            limit=limit,
            has_next=False,
        )

    async def get_chapter_pages(self, provider_chapter_id: str = "", provider_manga_id: str = "", data_saver: bool = False, **kwargs) -> ProviderPagesResult:
        if self.should_fail_pages:
            raise RuntimeError("Simulated provider failure")
        return ProviderPagesResult(
            provider_id=self.provider_id,
            provider_chapter_id=provider_chapter_id,
            pages=[
                ProviderPageItem(page_number=i + 1, image_url=url)
                for i, url in enumerate(self.pages_results)
            ],
        )

    async def close(self) -> None:
        pass


@pytest.mark.anyio
async def test_task015_title_unification_remanga_and_mangalib(test_db: sqlite3.Connection):
    """
    TASK 015 Requirement:
    Matching titles across ReManga and MangaLib are unified into one canonical manga card,
    with both source links recorded in manga_sources.
    """
    registry = ProviderRegistry()
    rem_prov = MockTestProvider("remanga", "ReManga")
    lib_prov = MockTestProvider("mangalib", "MangaLib")

    rem_prov.search_results = [
        ProviderMangaItem(
            provider_id="remanga",
            provider_manga_id="the-boxer_",
            title="Боксёр",
            alt_titles=["The Boxer"],
            description="История бокса от ReManga",
            cover_url="https://img3.reimg2.org/cover1.jpg",
            status="completed",
            release_year=2019,
            available_languages=["ru"],
        )
    ]

    lib_prov.search_results = [
        ProviderMangaItem(
            provider_id="mangalib",
            provider_manga_id="26198--the_boxer",
            title="Боксёр",
            alt_titles=["The Boxer"],
            description="История бокса от MangaLib",
            cover_url="https://cover.imglib.info/cover2.jpg",
            status="completed",
            release_year=2019,
            available_languages=["ru"],
        )
    ]

    registry.register(rem_prov)
    registry.register(lib_prov)

    catalog = CatalogService(conn=test_db, registry=registry)
    results = await catalog.search(query="Боксёр")

    # Should unify into 1 canonical manga
    assert len(results) == 1
    manga_id = results[0].id

    # Verify both sources are recorded in manga_sources
    cursor = test_db.cursor()
    cursor.execute("SELECT source_name, source_manga_id FROM manga_sources WHERE manga_id = ?", (manga_id,))
    sources = {r["source_name"]: r["source_manga_id"] for r in cursor.fetchall()}

    assert "remanga" in sources
    assert sources["remanga"] == "the-boxer_"
    assert "mangalib" in sources
    assert sources["mangalib"] == "26198--the_boxer"


@pytest.mark.anyio
async def test_task015_chapter_reconciliation_and_reserve_supplement(test_db: sqlite3.Connection):
    """
    TASK 015 Requirement:
    Chapters from ReManga (primary) are reconciled with MangaLib (reserve).
    Duplicate releases are deduplicated in favor of ReManga.
    Alternative translation teams are preserved.
    Missing chapters in ReManga are supplemented by MangaLib.
    """
    registry = ProviderRegistry()
    rem_prov = MockTestProvider("remanga", "ReManga")
    lib_prov = MockTestProvider("mangalib", "MangaLib")

    # ReManga has chapters 1 and 2
    rem_prov.chapters_results = [
        ProviderChapterItem(
            provider_id="remanga",
            provider_manga_id="the_gamer_",
            provider_chapter_id="rem-ch-1",
            chapter_number_raw="1",
            chapter_number_numeric=1.0,
            volume_number=1,
            title="Глава 1",
            language="ru",
            scanlation_group="GamerTeam",
        ),
        ProviderChapterItem(
            provider_id="remanga",
            provider_manga_id="the_gamer_",
            provider_chapter_id="rem-ch-2",
            chapter_number_raw="2",
            chapter_number_numeric=2.0,
            volume_number=1,
            title="Глава 2",
            language="ru",
            scanlation_group="GamerTeam",
        ),
    ]

    # MangaLib has chapter 1 (same group - should deduplicate), chapter 1 (different group "AltTeam" - preserve!), and chapter 13 (missing in remanga - supplement!)
    lib_prov.chapters_results = [
        ProviderChapterItem(
            provider_id="mangalib",
            provider_manga_id="382--the-gamer_",
            provider_chapter_id="lib-ch-1-dup",
            chapter_number_raw="1",
            chapter_number_numeric=1.0,
            volume_number=1,
            title="Глава 1",
            language="ru",
            scanlation_group="GamerTeam",
        ),
        ProviderChapterItem(
            provider_id="mangalib",
            provider_manga_id="382--the-gamer_",
            provider_chapter_id="lib-ch-1-alt",
            chapter_number_raw="1",
            chapter_number_numeric=1.0,
            volume_number=1,
            title="Глава 1 (Альтернативный перевод)",
            language="ru",
            scanlation_group="AltTeam",
        ),
        ProviderChapterItem(
            provider_id="mangalib",
            provider_manga_id="382--the-gamer_",
            provider_chapter_id="lib-ch-13",
            chapter_number_raw="13",
            chapter_number_numeric=13.0,
            volume_number=1,
            title="Глава 13",
            language="ru",
            scanlation_group="GamerTeam",
        ),
    ]

    registry.register(rem_prov)
    registry.register(lib_prov)

    catalog = CatalogService(conn=test_db, registry=registry)

    # Insert canonical manga with both sources
    cursor = test_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug, status) VALUES ('Игрок', 'the-gamer', 'ongoing')")
    manga_id = cursor.lastrowid
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'remanga', 'the_gamer_')", (manga_id,))
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangalib', '382--the-gamer_')", (manga_id,))
    test_db.commit()

    chapters = await catalog.sync_manga_chapters(manga_id)

    # Chapter 1 (GamerTeam from ReManga)
    # Chapter 1 (AltTeam from MangaLib)
    # Chapter 2 (GamerTeam from ReManga)
    # Chapter 13 (GamerTeam from MangaLib)
    assert len(chapters) == 4

    ch_nums = [c.chapter_number for c in chapters]
    assert 1.0 in ch_nums
    assert 2.0 in ch_nums
    assert 13.0 in ch_nums

    # Verify AltTeam is preserved
    scan_groups = {c.scanlation_group for c in chapters}
    assert "AltTeam" in scan_groups
    assert "GamerTeam" in scan_groups


@pytest.mark.anyio
async def test_task015_reader_fallback_transparent(test_db: sqlite3.Connection):
    """
    TASK 015 Requirement:
    Transparent fallback: if primary (ReManga) fails to return pages, reader falls back to MangaLib.
    """
    registry = ProviderRegistry()
    rem_prov = MockTestProvider("remanga", "ReManga")
    lib_prov = MockTestProvider("mangalib", "MangaLib")

    rem_prov.should_fail_pages = True  # Primary fails
    lib_prov.pages_results = [
        "https://img3.cdnrulib.link/page1.jpg",
        "https://img3.cdnrulib.link/page2.jpg",
    ]

    registry.register(rem_prov)
    registry.register(lib_prov)

    cursor = test_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Игрок', 'the-gamer')")
    manga_id = cursor.lastrowid
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'remanga', 'the_gamer_')", (manga_id,))
    rem_src_id = cursor.lastrowid
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangalib', '382--the-gamer_')", (manga_id,))
    lib_src_id = cursor.lastrowid

    # Insert chapter linked to canonical chapter
    cursor.execute("INSERT INTO canonical_chapters (manga_id, chapter_number, title) VALUES (?, 13.0, 'Глава 13')", (manga_id,))
    cc_id = cursor.lastrowid

    cursor.execute(
        """
        INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, canonical_chapter_id, chapter_number, title, language)
        VALUES (?, ?, 'rem-ch-13', ?, 13.0, 'Глава 13', 'ru')
        """,
        (manga_id, rem_src_id, cc_id),
    )
    rem_ch_id = cursor.lastrowid

    cursor.execute(
        """
        INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, canonical_chapter_id, chapter_number, title, language)
        VALUES (?, ?, 'lib-ch-13', ?, 13.0, 'Глава 13', 'ru')
        """,
        (manga_id, lib_src_id, cc_id),
    )
    lib_ch_id = cursor.lastrowid
    test_db.commit()

    reader = ReaderService(conn=test_db, registry=registry)
    detail = await reader.get_chapter_reader_detail(id_or_slug="the-gamer", chapter_id=rem_ch_id)

    # ReManga candidate failed, so fallback candidate MangaLib must have succeeded!
    assert len(detail.pages) == 2
    assert detail.pages[0].page_number == 1
    assert detail.pages[0].image_url == f"/api/manga/chapters/{lib_ch_id}/pages/1"

    cursor = test_db.cursor()
    cursor.execute("SELECT image_url FROM chapter_pages WHERE chapter_id = ? AND page_number = 1", (lib_ch_id,))
    row = cursor.fetchone()
    assert row["image_url"] == "https://img3.cdnrulib.link/page1.jpg"
