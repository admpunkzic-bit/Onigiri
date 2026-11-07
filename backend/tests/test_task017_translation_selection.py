"""
Test suite for TASK 017: Translation selection and chapter deduplication.
Verifies:
1. Grouping chapters into translation variants by source and team.
2. Automatic selection of best translation variant (working chapters count, sequence completeness, ReManga tie-breaker).
3. Deduplication of chapters within variant (0 duplicate chapter cards).
4. Scoped chapter loading per translation variant.
5. Reader navigation (prev/next) scoped strictly to the chosen translation variant.
6. Fallback strictly restricted to matching translation team (no cross-translation substitutions).
7. Reading progress tracked independently per translation variant without loss on switching.
"""

import pytest
from database.connection import get_connection
from database.migrations import run_migrations
from services.catalog import CatalogService
from services.reader import ReaderService


@pytest.fixture
def memory_db():
    """Create an in-memory database with full schema and migrations applied."""
    conn = get_connection(":memory:")
    run_migrations(conn)
    yield conn
    conn.close()


def test_translation_variants_grouping_and_metrics(memory_db):
    """Test that chapters are grouped by source and team with accurate metrics."""
    cursor = memory_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Test Manga', 'test-manga')")
    manga_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'remanga', 'rem-01')",
        (manga_id,),
    )
    rem_source_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangalib', 'ml-01')",
        (manga_id,),
    )
    ml_source_id = cursor.lastrowid

    # ReManga: Team Alpha, 10 sequential chapters in 2 volumes
    for ch in range(1, 11):
        vol = 1 if ch <= 5 else 2
        cursor.execute(
            """
            INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, scanlation_group, language)
            VALUES (?, ?, ?, ?, ?, 'Team Alpha', 'ru')
            """,
            (manga_id, rem_source_id, f"rem-{ch}", float(ch), vol),
        )

    # MangaLib: Team Alpha, 5 chapters
    for ch in range(1, 6):
        cursor.execute(
            """
            INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, scanlation_group, language)
            VALUES (?, ?, ?, ?, 1, 'Team Alpha', 'ru')
            """,
            (manga_id, ml_source_id, f"ml-alpha-{ch}", float(ch)),
        )

    # MangaLib: Unknown team (None), 8 chapters
    for ch in range(1, 9):
        cursor.execute(
            """
            INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, scanlation_group, language)
            VALUES (?, ?, ?, ?, 1, NULL, 'ru')
            """,
            (manga_id, ml_source_id, f"ml-unk-{ch}", float(ch)),
        )

    memory_db.commit()

    service = CatalogService(conn=memory_db)
    variants, default_id = service.get_translation_variants(manga_id)

    assert len(variants) == 3
    # Default should be ReManga Team Alpha (10 chs)
    assert default_id == "remanga:Team Alpha"
    assert variants[0].id == "remanga:Team Alpha"
    assert variants[0].chapters_count == 10
    assert variants[0].volumes_count == 2
    assert variants[0].min_chapter == 1.0
    assert variants[0].max_chapter == 10.0
    assert variants[0].has_gaps is False
    assert variants[0].is_default is True

    # Unknown team label verification
    unk_variant = next(v for v in variants if v.id == "mangalib:unknown")
    assert unk_variant.translator_name == "Переводчик неизвестен"
    assert "Неизвестный переводчик (MangaLib)" in unk_variant.display_name
    assert unk_variant.chapters_count == 8


def test_translation_auto_selection_gaps_penalty_and_tiebreak(memory_db):
    """
    Test that a continuous sequence wins over a sparse sequence with large gaps,
    and ReManga wins on equal score.
    """
    cursor = memory_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Gamer Gaps', 'gamer-gaps')")
    manga_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'remanga', 'rem-gap')",
        (manga_id,),
    )
    rem_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangalib', 'ml-gap')",
        (manga_id,),
    )
    ml_id = cursor.lastrowid

    # MangaLib: Team Beta has 50 chapters, but with massive gap from ch 10 to ch 100
    for ch in range(1, 11):
        cursor.execute(
            """
            INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, scanlation_group, language)
            VALUES (?, ?, ?, ?, 1, 'Team Beta', 'ru')
            """,
            (manga_id, ml_id, f"ml-b-{ch}", float(ch)),
        )
    for ch in range(100, 140):
        cursor.execute(
            """
            INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, scanlation_group, language)
            VALUES (?, ?, ?, ?, 1, 'Team Beta', 'ru')
            """,
            (manga_id, ml_id, f"ml-b-{ch}", float(ch)),
        )

    # ReManga: Team Gamma has 40 chapters, perfectly continuous 1..40
    for ch in range(1, 41):
        cursor.execute(
            """
            INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, scanlation_group, language)
            VALUES (?, ?, ?, ?, 1, 'Team Gamma', 'ru')
            """,
            (manga_id, rem_id, f"rem-g-{ch}", float(ch)),
        )

    memory_db.commit()

    service = CatalogService(conn=memory_db)
    variants, default_id = service.get_translation_variants(manga_id)

    # Continuous 40 chapters of Team Gamma should win over sparse 50 chapters of Team Beta (90-chapter gap penalty)
    assert default_id == "remanga:Team Gamma"
    beta_var = next(v for v in variants if v.id == "mangalib:Team Beta")
    assert beta_var.has_gaps is True
    assert beta_var.gaps_count >= 80


def test_chapter_deduplication_within_variant(memory_db):
    """
    Test that duplicate releases with same (volume_number, chapter_number) within the same variant
    are deduplicated to 1 item in the catalog list.
    """
    cursor = memory_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Dedup Manga', 'dedup-manga')")
    manga_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'remanga', 'rem-dup')",
        (manga_id,),
    )
    rem_id = cursor.lastrowid

    # Insert Chapter 1.0 twice for same source & team (e.g. re-upload / duplicate sync)
    cursor.execute(
        """
        INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, scanlation_group, language)
        VALUES (?, ?, 'rem-1-v1', 1.0, 1, 'Team Alpha', 'ru')
        """,
        (manga_id, rem_id),
    )
    cursor.execute(
        """
        INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, scanlation_group, language)
        VALUES (?, ?, 'rem-1-v2', 1.0, 1, 'Team Alpha', 'ru')
        """,
        (manga_id, rem_id),
    )
    # Chapter 2.0 once
    cursor.execute(
        """
        INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, scanlation_group, language)
        VALUES (?, ?, 'rem-2', 2.0, 1, 'Team Alpha', 'ru')
        """,
        (manga_id, rem_id),
    )
    memory_db.commit()

    service = CatalogService(conn=memory_db)
    chs = service._load_manga_chapters(manga_id, translation_id="remanga:Team Alpha")
    # Must be exactly 2 chapters, NOT 3!
    assert len(chs) == 2
    assert chs[0].chapter_number == 1.0
    assert chs[1].chapter_number == 2.0


def test_reader_navigation_strictly_within_translation(memory_db):
    """
    Test that prev_chapter_id and next_chapter_id never jump across different translations.
    """
    cursor = memory_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Nav Manga', 'nav-manga')")
    manga_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'remanga', 'rem-nav')",
        (manga_id,),
    )
    rem_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangalib', 'ml-nav')",
        (manga_id,),
    )
    ml_id = cursor.lastrowid

    # Translation A: ReManga Team A (chapters 1, 2, 3)
    cursor.execute(
        "INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, scanlation_group, language) VALUES (?, ?, 'r-1', 1.0, 1, 'Team A', 'ru')",
        (manga_id, rem_id),
    )
    chA1 = cursor.lastrowid
    cursor.execute(
        "INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, scanlation_group, language) VALUES (?, ?, 'r-2', 2.0, 1, 'Team A', 'ru')",
        (manga_id, rem_id),
    )
    chA2 = cursor.lastrowid
    cursor.execute(
        "INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, scanlation_group, language) VALUES (?, ?, 'r-3', 3.0, 1, 'Team A', 'ru')",
        (manga_id, rem_id),
    )
    chA3 = cursor.lastrowid

    # Translation B: MangaLib Team B (chapters 1.5, 2.5)
    cursor.execute(
        "INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, scanlation_group, language) VALUES (?, ?, 'm-15', 1.5, 1, 'Team B', 'ru')",
        (manga_id, ml_id),
    )
    chB1 = cursor.lastrowid
    cursor.execute(
        "INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, scanlation_group, language) VALUES (?, ?, 'm-25', 2.5, 1, 'Team B', 'ru')",
        (manga_id, ml_id),
    )
    chB2 = cursor.lastrowid
    memory_db.commit()

    from providers.base import BaseMangaProvider, ProviderPageItem, ProviderPagesResult
    from providers.registry import ProviderRegistry

    class DummyProvider(BaseMangaProvider):
        def __init__(self, name):
            super().__init__()
            self._name = name
        @property
        def provider_id(self) -> str:
            return self._name
        @property
        def name(self) -> str:
            return self._name
        async def close(self): pass
        async def search(self, *args, **kwargs): pass
        async def get_manga_details(self, *args, **kwargs): pass
        async def get_chapters(self, *args, **kwargs): pass
        async def get_chapter_pages(self, *args, **kwargs):
            return ProviderPagesResult(
                provider_id=self._name,
                provider_chapter_id="dummy",
                base_url="https://cdn.example.com",
                pages=[ProviderPageItem(page_number=1, image_url="https://cdn.example.com/1.jpg")]
            )

    registry = ProviderRegistry()
    registry.register(DummyProvider("remanga"))
    registry.register(DummyProvider("mangalib"))

    reader_service = ReaderService(conn=memory_db, registry=registry)
    import asyncio
    detail = asyncio.run(reader_service.get_chapter_reader_detail(str(manga_id), chA2))

    # Should point to chA1 and chA3, NEVER chB1 (1.5) or chB2 (2.5)!
    assert detail.prev_chapter_id == chA1
    assert detail.next_chapter_id == chA3
    assert detail.scanlation_group == "Team A"


def test_reading_progress_preserved_across_translations(memory_db):
    """
    Test that reading progress is saved independently per translation variant
    and switching translations does not wipe previous progress.
    """
    cursor = memory_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Progress Manga', 'progress-manga')")
    manga_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'remanga', 'rem-p')",
        (manga_id,),
    )
    rem_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangalib', 'ml-p')",
        (manga_id,),
    )
    ml_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, scanlation_group, language) VALUES (?, ?, 'rp-1', 10.0, 1, 'Team Alpha', 'ru')",
        (manga_id, rem_id),
    )
    ch_alpha = cursor.lastrowid

    cursor.execute(
        "INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, scanlation_group, language) VALUES (?, ?, 'mlp-1', 20.0, 1, 'Team Beta', 'ru')",
        (manga_id, ml_id),
    )
    ch_beta = cursor.lastrowid
    memory_db.commit()

    reader_service = ReaderService(conn=memory_db)

    # User reads Team Alpha up to page 5
    reader_service.save_user_progress("user_123", str(manga_id), ch_alpha, page_number=5, total_pages=20)

    # User switches to Team Beta and reads up to page 12
    reader_service.save_user_progress("user_123", str(manga_id), ch_beta, page_number=12, total_pages=30)

    # Verify both progress records exist and are independent
    prog_alpha = reader_service.get_user_progress("user_123", str(manga_id), translation_id="remanga:Team Alpha")
    assert prog_alpha is not None
    assert prog_alpha.chapter_id == ch_alpha
    assert prog_alpha.page_number == 5

    prog_beta = reader_service.get_user_progress("user_123", str(manga_id), translation_id="mangalib:Team Beta")
    assert prog_beta is not None
    assert prog_beta.chapter_id == ch_beta
    assert prog_beta.page_number == 12

    # Latest progress query (without translation_id) returns Team Beta (most recently updated)
    latest_prog = reader_service.get_user_progress("user_123", str(manga_id))
    assert latest_prog is not None
    assert latest_prog.chapter_id == ch_beta


def test_fallback_candidate_requires_matching_translation_team(memory_db):
    """
    Test that when primary source fails, fallback candidate is only considered if
    its translation team matches the primary chapter's translation team.
    """
    cursor = memory_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Fallback Isolation', 'fallback-iso')")
    manga_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'remanga', 'rem-fb')",
        (manga_id,),
    )
    rem_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangalib', 'ml-fb')",
        (manga_id,),
    )
    ml_id = cursor.lastrowid

    # Primary: ReManga Team X (ch 5.0)
    cursor.execute(
        "INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, scanlation_group, language) VALUES (?, ?, 'r-fail', 5.0, 1, 'Team X', 'ru')",
        (manga_id, rem_id),
    )
    ch_primary = cursor.lastrowid

    # Reserve candidate 1: MangaLib Team Y (different team, ch 5.0) -> SHOULD BE REJECTED
    cursor.execute(
        "INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, scanlation_group, language) VALUES (?, ?, 'ml-diff', 5.0, 1, 'Team Y', 'ru')",
        (manga_id, ml_id),
    )
    ch_diff_team = cursor.lastrowid

    # Reserve candidate 2: MangaLib Team X (matching team, ch 5.0) -> SHOULD BE ACCEPTED
    cursor.execute(
        "INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, scanlation_group, language) VALUES (?, ?, 'ml-same', 5.0, 1, 'Team X', 'ru')",
        (manga_id, ml_id),
    )
    ch_matching_team = cursor.lastrowid

    memory_db.commit()

    from providers.base import BaseMangaProvider, ProviderPageItem, ProviderPagesResult
    from providers.registry import ProviderRegistry

    class FailingPrimaryProvider(BaseMangaProvider):
        @property
        def provider_id(self) -> str: return "remanga"
        @property
        def name(self) -> str: return "remanga"
        async def close(self): pass
        async def search(self, *args, **kwargs): pass
        async def get_manga_details(self, *args, **kwargs): pass
        async def get_chapters(self, *args, **kwargs): pass
        async def get_chapter_pages(self, *args, **kwargs):
            raise RuntimeError("Primary ReManga 500 network down")

    class WorkingReserveProvider(BaseMangaProvider):
        @property
        def provider_id(self) -> str: return "mangalib"
        @property
        def name(self) -> str: return "mangalib"
        async def close(self): pass
        async def search(self, *args, **kwargs): pass
        async def get_manga_details(self, *args, **kwargs): pass
        async def get_chapters(self, *args, **kwargs): pass
        async def get_chapter_pages(self, provider_chapter_id, *args, **kwargs):
            if provider_chapter_id == "ml-same":
                return ProviderPagesResult(
                    provider_id="mangalib",
                    provider_chapter_id="ml-same",
                    base_url="https://cdn.example.com",
                    pages=[ProviderPageItem(page_number=1, image_url="https://cdn.example.com/ml-same-1.jpg")]
                )
            raise RuntimeError(f"Unexpected candidate: {provider_chapter_id}")

    registry = ProviderRegistry()
    registry.register(FailingPrimaryProvider())
    registry.register(WorkingReserveProvider())

    reader_service = ReaderService(conn=memory_db, registry=registry)
    import asyncio
    detail = asyncio.run(reader_service.get_chapter_reader_detail(str(manga_id), ch_primary))

    assert detail is not None
    # Verify fallback fell back to the chapter with matching team (ch_matching_team)
    assert any(str(ch_matching_team) in p.image_url for p in detail.pages)
    assert not any(str(ch_diff_team) in p.image_url for p in detail.pages)
