"""
Tests for multi-source chapter reconciliation, canonical chapters,
and preservation of reading progress.
"""

import sqlite3
import pytest
from database.migrations import run_migrations


@pytest.fixture
def test_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    yield conn
    conn.close()


def test_canonical_chapters_reconciliation_multi_variants(test_db: sqlite3.Connection):
    """
    If multiple translation groups (or sources) translate the same chapter number,
    exactly ONE canonical_chapter is created, and all chapter rows are linked to it.
    """
    cursor = test_db.cursor()

    # 1. Insert manga
    cursor.execute(
        "INSERT INTO manga (title, slug) VALUES ('Test Manga', 'test-manga')"
    )
    manga_id = cursor.lastrowid

    # 2. Insert two sources
    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangadex', 'md-1')",
        (manga_id,),
    )
    src_md = cursor.lastrowid

    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangachan', 'mc-1')",
        (manga_id,),
    )
    src_mc = cursor.lastrowid

    # 3. Insert chapter 1 translated by Team Alpha (MangaDex)
    cursor.execute(
        """
        INSERT INTO chapters (
            manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number,
            title, language, scanlation_group
        )
        VALUES (?, ?, 'md-ch1', 1.0, 1, 'Chapter One', 'ru', 'Team Alpha')
        """,
        (manga_id, src_md),
    )
    ch_alpha_id = cursor.lastrowid

    # 4. Insert chapter 1 translated by Team Beta (Manga-Chan)
    cursor.execute(
        """
        INSERT INTO chapters (
            manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number,
            title, language, scanlation_group
        )
        VALUES (?, ?, 'mc-ch1', 1.0, 1, 'Глава 1: Начало', 'ru', 'Team Beta')
        """,
        (manga_id, src_mc),
    )
    ch_beta_id = cursor.lastrowid

    # 5. Insert chapter 2 (only Manga-Chan)
    cursor.execute(
        """
        INSERT INTO chapters (
            manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number,
            title, language, scanlation_group
        )
        VALUES (?, ?, 'mc-ch2', 2.0, 1, 'Глава 2', 'ru', 'Team Beta')
        """,
        (manga_id, src_mc),
    )
    ch2_id = cursor.lastrowid

    # 6. Reconcile into canonical_chapters
    cursor.execute(
        """
        INSERT OR IGNORE INTO canonical_chapters (manga_id, chapter_number, volume_number, title)
        SELECT manga_id, chapter_number, volume_number, title
        FROM chapters
        WHERE manga_id = ?
        ORDER BY id ASC
        """,
        (manga_id,),
    )
    cursor.execute(
        """
        UPDATE chapters
        SET canonical_chapter_id = (
            SELECT cc.id
            FROM canonical_chapters cc
            WHERE cc.manga_id = chapters.manga_id
              AND cc.chapter_number = chapters.chapter_number
        )
        WHERE manga_id = ? AND canonical_chapter_id IS NULL
        """,
        (manga_id,),
    )
    test_db.commit()

    # Assert: Exactly 2 canonical chapters created (Chapter 1 and Chapter 2)
    cursor.execute("SELECT id, chapter_number FROM canonical_chapters WHERE manga_id = ? ORDER BY chapter_number", (manga_id,))
    canonical_rows = cursor.fetchall()
    assert len(canonical_rows) == 2
    assert canonical_rows[0]["chapter_number"] == 1.0
    assert canonical_rows[1]["chapter_number"] == 2.0

    can1_id = canonical_rows[0]["id"]
    can2_id = canonical_rows[1]["id"]

    # Assert: Both Team Alpha and Team Beta chapter 1 are linked to canonical chapter 1
    cursor.execute("SELECT canonical_chapter_id FROM chapters WHERE id = ?", (ch_alpha_id,))
    assert cursor.fetchone()[0] == can1_id

    cursor.execute("SELECT canonical_chapter_id FROM chapters WHERE id = ?", (ch_beta_id,))
    assert cursor.fetchone()[0] == can1_id

    # Assert: Chapter 2 is linked to canonical chapter 2
    cursor.execute("SELECT canonical_chapter_id FROM chapters WHERE id = ?", (ch2_id,))
    assert cursor.fetchone()[0] == can2_id


def test_reading_progress_preserves_chapter_id(test_db: sqlite3.Connection):
    """
    Ensure user_reading_progress correctly links to specific chapter and
    remains completely valid across canonical chapter reconciliation.
    """
    cursor = test_db.cursor()

    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Manga Progress', 'manga-prog')")
    manga_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangachan', 'mc-p')",
        (manga_id,),
    )
    src_id = cursor.lastrowid

    cursor.execute(
        """
        INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, title)
        VALUES (?, ?, 'mc-p-ch5', 5.0, 'Chapter 5')
        """,
        (manga_id, src_id),
    )
    ch5_id = cursor.lastrowid

    # Save progress
    user_id = "tg_12345"
    cursor.execute(
        """
        INSERT INTO user_reading_progress (user_id, manga_id, chapter_id, page_number, total_pages)
        VALUES (?, ?, ?, 12, 24)
        """,
        (user_id, manga_id, ch5_id),
    )
    test_db.commit()

    # Reconcile canonical chapters
    cursor.execute(
        """
        INSERT OR IGNORE INTO canonical_chapters (manga_id, chapter_number, volume_number, title)
        SELECT manga_id, chapter_number, volume_number, title FROM chapters WHERE manga_id = ?
        """,
        (manga_id,),
    )
    test_db.commit()

    # Verify progress is intact
    cursor.execute("SELECT chapter_id, page_number FROM user_reading_progress WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    assert row["chapter_id"] == ch5_id
    assert row["page_number"] == 12

    # Check foreign keys
    cursor.execute("PRAGMA foreign_key_check")
    assert cursor.fetchall() == []
