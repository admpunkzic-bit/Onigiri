import sqlite3
import pytest
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


class MockVolumeProvider(BaseMangaProvider):
    def __init__(self, provider_id: str, name: str):
        self._provider_id = provider_id
        self._name = name
        self.chapters_results: List[ProviderChapterItem] = []
        self.pages_results: List[str] = ["https://example.com/p1.jpg"]

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def name(self) -> str:
        return self._name

    async def search(self, query: str, page: int = 1, limit: int = 20, languages: Optional[List[str]] = None) -> ProviderSearchResult:
        return ProviderSearchResult(provider_id=self.provider_id, items=[], total=0, page=page, limit=limit, has_next=False)

    async def get_manga_details(self, provider_manga_id: str) -> Optional[ProviderMangaItem]:
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
        return ProviderPagesResult(
            provider_id=self.provider_id,
            provider_chapter_id=provider_chapter_id,
            pages=[ProviderPageItem(page_number=i + 1, image_url=url) for i, url in enumerate(self.pages_results)],
        )

    async def close(self) -> None:
        pass


@pytest.mark.anyio
async def test_case_1_and_2_same_chapter_number_different_volumes_and_ordering(test_db: sqlite3.Connection):
    """
    Case 1 & 2:
    - Same chapter number in different volumes (e.g. Vol 5 Ch 1, Vol 6 Ch 1, Vol 7 Ch 1).
    - Sequence of chapters within a volume.
    Chapters must not merge and must sort by volume first, then chapter number.
    """
    cursor = test_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Test Gamer', 'test-gamer')")
    manga_id = cursor.lastrowid
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'remanga', 'tg-1')", (manga_id,))
    src_id = cursor.lastrowid

    prov = MockVolumeProvider("remanga", "ReManga")
    prov.chapters_results = [
        # Vol 5: Ch 1, 2
        ProviderChapterItem(provider_id="remanga", provider_manga_id="tg-1", provider_chapter_id="c5-1", chapter_number_raw="1", chapter_number_numeric=1.0, volume_number=5, language="ru"),
        ProviderChapterItem(provider_id="remanga", provider_manga_id="tg-1", provider_chapter_id="c5-2", chapter_number_raw="2", chapter_number_numeric=2.0, volume_number=5, language="ru"),
        # Vol 6: Ch 1, 2
        ProviderChapterItem(provider_id="remanga", provider_manga_id="tg-1", provider_chapter_id="c6-1", chapter_number_raw="1", chapter_number_numeric=1.0, volume_number=6, language="ru"),
        ProviderChapterItem(provider_id="remanga", provider_manga_id="tg-1", provider_chapter_id="c6-2", chapter_number_raw="2", chapter_number_numeric=2.0, volume_number=6, language="ru"),
        # Vol 7: Ch 1
        ProviderChapterItem(provider_id="remanga", provider_manga_id="tg-1", provider_chapter_id="c7-1", chapter_number_raw="1", chapter_number_numeric=1.0, volume_number=7, language="ru"),
    ]

    reg = ProviderRegistry()
    reg.register(prov)
    catalog = CatalogService(conn=test_db, registry=reg)

    chapters = await catalog.sync_manga_chapters(manga_id)
    assert len(chapters) == 5

    # Check distinct canonical chapters
    cursor.execute("SELECT DISTINCT canonical_chapter_id FROM chapters WHERE manga_id = ?", (manga_id,))
    canonical_ids = cursor.fetchall()
    assert len(canonical_ids) == 5, "Each volume's chapter must receive a distinct canonical_chapter_id"

    # Check ordering in 'asc': Vol 5 Ch 1, Vol 5 Ch 2, Vol 6 Ch 1, Vol 6 Ch 2, Vol 7 Ch 1
    vols_and_nums = [(c.volume_number, c.chapter_number) for c in chapters]
    assert vols_and_nums == [
        (5, 1.0),
        (5, 2.0),
        (6, 1.0),
        (6, 2.0),
        (7, 1.0),
    ]

    # Check ordering in 'desc': Vol 7 Ch 1, Vol 6 Ch 2, Vol 6 Ch 1, Vol 5 Ch 2, Vol 5 Ch 1
    chapters_desc = await catalog.get_chapters_for_manga("test-gamer", order="desc")
    vols_and_nums_desc = [(c.volume_number, c.chapter_number) for c in chapters_desc]
    assert vols_and_nums_desc == [
        (7, 1.0),
        (6, 2.0),
        (6, 1.0),
        (5, 2.0),
        (5, 1.0),
    ]


@pytest.mark.anyio
async def test_case_3_chapters_without_volume_number(test_db: sqlite3.Connection):
    """
    Case 3:
    Chapters without volume number (volume_number is None):
    - Prologue (ch <= 0) appears before Volume 1.
    - Regular chapters without volume are preserved without synthetic volume invented.
    """
    cursor = test_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Test Volumeless', 'test-volumeless')")
    manga_id = cursor.lastrowid
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'remanga', 'tv-1')", (manga_id,))

    prov = MockVolumeProvider("remanga", "ReManga")
    prov.chapters_results = [
        # Chapter 0 (prologue) without volume
        ProviderChapterItem(provider_id="remanga", provider_manga_id="tv-1", provider_chapter_id="c0", chapter_number_raw="0", chapter_number_numeric=0.0, volume_number=None, language="ru"),
        # Vol 1 Ch 1
        ProviderChapterItem(provider_id="remanga", provider_manga_id="tv-1", provider_chapter_id="c1", chapter_number_raw="1", chapter_number_numeric=1.0, volume_number=1, language="ru"),
        # Vol 1 Ch 2
        ProviderChapterItem(provider_id="remanga", provider_manga_id="tv-1", provider_chapter_id="c2", chapter_number_raw="2", chapter_number_numeric=2.0, volume_number=1, language="ru"),
    ]

    reg = ProviderRegistry()
    reg.register(prov)
    catalog = CatalogService(conn=test_db, registry=reg)

    chapters = await catalog.sync_manga_chapters(manga_id)
    assert len(chapters) == 3

    # Volume numbers preserved exactly
    assert chapters[0].chapter_number == 0.0
    assert chapters[0].volume_number is None
    assert chapters[1].chapter_number == 1.0
    assert chapters[1].volume_number == 1
    assert chapters[2].chapter_number == 2.0
    assert chapters[2].volume_number == 1


@pytest.mark.anyio
async def test_case_4_and_5_fractional_and_special_chapters(test_db: sqlite3.Connection):
    """
    Case 4 & 5:
    Fractional (e.g. 1.5, 73.1) and special/bonus chapters.
    """
    cursor = test_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Test Special', 'test-special')")
    manga_id = cursor.lastrowid
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'remanga', 'ts-1')", (manga_id,))

    prov = MockVolumeProvider("remanga", "ReManga")
    prov.chapters_results = [
        ProviderChapterItem(provider_id="remanga", provider_manga_id="ts-1", provider_chapter_id="c1", chapter_number_raw="1", chapter_number_numeric=1.0, volume_number=1, language="ru"),
        ProviderChapterItem(provider_id="remanga", provider_manga_id="ts-1", provider_chapter_id="c1.5", chapter_number_raw="1.5", chapter_number_numeric=1.5, volume_number=1, title="Экстра", language="ru"),
        ProviderChapterItem(provider_id="remanga", provider_manga_id="ts-1", provider_chapter_id="c2", chapter_number_raw="2", chapter_number_numeric=2.0, volume_number=1, language="ru"),
    ]

    reg = ProviderRegistry()
    reg.register(prov)
    catalog = CatalogService(conn=test_db, registry=reg)

    chapters = await catalog.sync_manga_chapters(manga_id)
    assert len(chapters) == 3
    nums = [c.chapter_number for c in chapters]
    assert nums == [1.0, 1.5, 2.0]


@pytest.mark.anyio
async def test_case_6_same_chapters_remanga_and_mangalib_deduplication(test_db: sqlite3.Connection):
    """
    Case 6:
    Identical chapters from ReManga and MangaLib in the same volume with same scanlation group
    must deduplicate in favor of ReManga.
    """
    cursor = test_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Test Dedup', 'test-dedup')")
    manga_id = cursor.lastrowid
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'remanga', 'rem-dup')", (manga_id,))
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangalib', 'lib-dup')", (manga_id,))

    rem_prov = MockVolumeProvider("remanga", "ReManga")
    lib_prov = MockVolumeProvider("mangalib", "MangaLib")

    rem_prov.chapters_results = [
        ProviderChapterItem(provider_id="remanga", provider_manga_id="rem-dup", provider_chapter_id="rem-1", chapter_number_raw="1", chapter_number_numeric=1.0, volume_number=2, scanlation_group="TeamA", language="ru"),
    ]
    lib_prov.chapters_results = [
        ProviderChapterItem(provider_id="mangalib", provider_manga_id="lib-dup", provider_chapter_id="lib-1", chapter_number_raw="1", chapter_number_numeric=1.0, volume_number=2, scanlation_group="TeamA", language="ru"),
    ]

    reg = ProviderRegistry()
    reg.register(rem_prov)
    reg.register(lib_prov)
    catalog = CatalogService(conn=test_db, registry=reg)

    chapters = await catalog.sync_manga_chapters(manga_id)
    # Identical release in same volume 2: deduplicated!
    assert len(chapters) == 1
    assert chapters[0].source_chapter_id == "rem-1"


@pytest.mark.anyio
async def test_case_7_same_chapter_number_different_volumes_different_sources(test_db: sqlite3.Connection):
    """
    Case 7:
    Same chapter number, but different volumes across different sources:
    ReManga has Vol 1 Ch 1.
    MangaLib has Vol 2 Ch 1.
    Must NOT be treated as duplicates! Both must be preserved under their respective volumes.
    """
    cursor = test_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Test CrossVol', 'test-crossvol')")
    manga_id = cursor.lastrowid
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'remanga', 'rem-cv')", (manga_id,))
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangalib', 'lib-cv')", (manga_id,))

    rem_prov = MockVolumeProvider("remanga", "ReManga")
    lib_prov = MockVolumeProvider("mangalib", "MangaLib")

    rem_prov.chapters_results = [
        ProviderChapterItem(provider_id="remanga", provider_manga_id="rem-cv", provider_chapter_id="rem-v1-c1", chapter_number_raw="1", chapter_number_numeric=1.0, volume_number=1, language="ru"),
    ]
    lib_prov.chapters_results = [
        ProviderChapterItem(provider_id="mangalib", provider_manga_id="lib-cv", provider_chapter_id="lib-v2-c1", chapter_number_raw="1", chapter_number_numeric=1.0, volume_number=2, language="ru"),
    ]

    reg = ProviderRegistry()
    reg.register(rem_prov)
    reg.register(lib_prov)
    catalog = CatalogService(conn=test_db, registry=reg)

    chapters = await catalog.sync_manga_chapters(manga_id)
    assert len(chapters) == 2
    assert (chapters[0].volume_number, chapters[0].chapter_number) == (1, 1.0)
    assert (chapters[1].volume_number, chapters[1].chapter_number) == (2, 1.0)


@pytest.mark.anyio
async def test_case_8_idempotent_sync_no_duplicates(test_db: sqlite3.Connection):
    """
    Case 8:
    Repeated sync runs must be 100% idempotent without generating duplicate records.
    """
    cursor = test_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Test Idempotency', 'test-idemp')")
    manga_id = cursor.lastrowid
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'remanga', 'rem-idemp')", (manga_id,))

    rem_prov = MockVolumeProvider("remanga", "ReManga")
    rem_prov.chapters_results = [
        ProviderChapterItem(provider_id="remanga", provider_manga_id="rem-idemp", provider_chapter_id="rem-c1", chapter_number_raw="1", chapter_number_numeric=1.0, volume_number=1, language="ru"),
        ProviderChapterItem(provider_id="remanga", provider_manga_id="rem-idemp", provider_chapter_id="rem-c2", chapter_number_raw="2", chapter_number_numeric=2.0, volume_number=1, language="ru"),
    ]

    reg = ProviderRegistry()
    reg.register(rem_prov)
    catalog = CatalogService(conn=test_db, registry=reg)

    first_sync = await catalog.sync_manga_chapters(manga_id)
    assert len(first_sync) == 2

    second_sync = await catalog.sync_manga_chapters(manga_id)
    assert len(second_sync) == 2

    cursor.execute("SELECT COUNT(*) FROM chapters WHERE manga_id = ?", (manga_id,))
    assert cursor.fetchone()[0] == 2
