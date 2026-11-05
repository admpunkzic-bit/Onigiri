"""
Comprehensive tests for SQLite data layer, migrations, integrity triggers,
FTS5 full-text search, domain models, Pydantic schemas and seed data.
"""

import sqlite3
import pytest
from pathlib import Path

from database.connection import get_connection, init_db
from database.migrations import (
    MIGRATIONS,
    is_fts5_available,
    run_migrations,
    search_manga,
    slugify,
)
from models.manga import Author, Chapter, ChapterPage, Genre, Manga, MangaSource
from schemas.manga import (
    AuthorRead,
    ChapterRead,
    GenreRead,
    MangaDetailRead,
    MangaListRead,
    MangaSourceRead,
)
from services.seed import seed_data


@pytest.fixture
def memory_db():
    """Create an in-memory SQLite connection with WAL/Foreign Keys enabled."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    yield conn
    conn.close()


@pytest.fixture
def migrated_db(tmp_path: Path):
    """Create a temporary isolated SQLite database file with all migrations applied."""
    db_file = tmp_path / "test_catalog.db"
    conn = get_connection(db_file)
    run_migrations(conn)
    yield conn
    conn.close()


# ==============================================================================
# 1. Slugify utility tests
# ==============================================================================

def test_slugify():
    assert slugify("Hello World") == "hello-world"
    assert slugify("Хроники Онигири!") == "khroniki-onigiri"
    assert slugify("Cat Cafe & Magic #1") == "cat-cafe-magic-1"
    assert slugify("---Leading and Trailing---") == "leading-and-trailing"
    assert slugify("") == "item"


# ==============================================================================
# 2. Migration over legacy schema (Safe migration & zero data loss)
# ==============================================================================

def test_migration_preserves_legacy_data(tmp_path: Path):
    """
    Verify that an existing database with the old TASK 001 schema:
    (id, title, description, cover_url, created_at)
    is safely upgraded without data loss and existing rows get valid slugs.
    """
    db_file = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    # 1. Create legacy schema
    conn.execute(
        """
        CREATE TABLE manga (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            cover_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # 2. Insert legacy row
    conn.execute(
        """
        INSERT INTO manga (title, description, cover_url)
        VALUES ('Берсерк', 'Легендарная манга Кэнтаро Миуры', 'https://example.com/berserk.jpg')
        """
    )
    conn.commit()

    # Verify initial row
    cur = conn.cursor()
    cur.execute("SELECT * FROM manga")
    initial_row = cur.fetchone()
    assert initial_row["title"] == "Берсерк"
    assert "slug" not in initial_row.keys()

    # 3. Apply migrations
    run_migrations(conn)

    # 4. Verify upgraded schema and preserved data
    cur.execute("SELECT * FROM manga WHERE id = 1")
    upgraded_row = cur.fetchone()
    assert upgraded_row["title"] == "Берсерк"
    assert upgraded_row["description"] == "Легендарная манга Кэнтаро Миуры"
    assert upgraded_row["cover_url"] == "https://example.com/berserk.jpg"
    assert upgraded_row["slug"] == "berserk"
    assert upgraded_row["status"] == "ongoing"
    assert upgraded_row["rating"] == 0.0

    conn.close()


# ==============================================================================
# 3. Idempotency of migrations
# ==============================================================================

def test_migration_idempotency(migrated_db: sqlite3.Connection):
    """Running run_migrations multiple times must be completely idempotent."""
    # Run second and third time
    run_migrations(migrated_db)
    run_migrations(migrated_db)

    cursor = migrated_db.cursor()
    cursor.execute("SELECT COUNT(*) FROM schema_migrations")
    assert cursor.fetchone()[0] == 5


# ==============================================================================
# 4. Foreign Key Constraints
# ==============================================================================

def test_foreign_key_constraints(migrated_db: sqlite3.Connection):
    """Foreign keys must prevent inserting orphan records."""
    cursor = migrated_db.cursor()

    # Inserting manga_source with invalid manga_id must fail
    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute(
            """
            INSERT INTO manga_sources (manga_id, source_name, source_manga_id)
            VALUES (9999, 'mangadex', 'md-9999')
            """
        )

    # Inserting chapter_page with invalid chapter_id must fail
    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute(
            """
            INSERT INTO chapter_pages (chapter_id, page_number, image_url)
            VALUES (9999, 1, 'https://example.com/orphan.jpg')
            """
        )


# ==============================================================================
# 5. Unique Constraints
# ==============================================================================

def test_unique_constraints(migrated_db: sqlite3.Connection):
    cursor = migrated_db.cursor()

    # Insert valid manga
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Test Manga', 'test-manga')")
    migrated_db.commit()

    # Duplicate slug must fail
    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute("INSERT INTO manga (title, slug) VALUES ('Duplicate', 'test-manga')")

    # Duplicate genre slug must fail
    cursor.execute("INSERT INTO genres (name, slug) VALUES ('Action', 'action')")
    migrated_db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute("INSERT INTO genres (name, slug) VALUES ('Action 2', 'action')")


# ==============================================================================
# 6. Chapter Manga ID Integrity Trigger
# ==============================================================================

def test_chapter_manga_id_trigger(migrated_db: sqlite3.Connection):
    """
    Ensure chapters cannot be associated with a manga_id that does not match
    the manga_id belonging to manga_sources.
    """
    cursor = migrated_db.cursor()

    # Create two different manga
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Manga 1', 'manga-1') RETURNING id")
    manga1_id = cursor.fetchone()["id"]
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Manga 2', 'manga-2') RETURNING id")
    manga2_id = cursor.fetchone()["id"]

    # Source belonging to Manga 1
    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'src1', 's1') RETURNING id",
        (manga1_id,),
    )
    source_manga1_id = cursor.fetchone()["id"]
    migrated_db.commit()

    # Valid insert: chapter manga_id matches source manga_id
    cursor.execute(
        """
        INSERT INTO chapters (manga_id, manga_source_id, chapter_number, title)
        VALUES (?, ?, 1.0, 'Chapter 1')
        """,
        (manga1_id, source_manga1_id),
    )
    migrated_db.commit()

    # Invalid insert: chapter manga_id (manga2_id) != source's manga_id (manga1_id)
    with pytest.raises(sqlite3.IntegrityError, match="Foreign key mismatch"):
        cursor.execute(
            """
            INSERT INTO chapters (manga_id, manga_source_id, chapter_number, title)
            VALUES (?, ?, 2.0, 'Mismatched Chapter')
            """,
            (manga2_id, source_manga1_id),
        )

    # Invalid update: updating chapter to mismatched manga_id
    with pytest.raises(sqlite3.IntegrityError, match="Foreign key mismatch"):
        cursor.execute(
            """
            UPDATE chapters SET manga_id = ? WHERE manga_source_id = ? AND chapter_number = 1.0
            """,
            (manga2_id, source_manga1_id),
        )


# ==============================================================================
# 7. Non-integer Chapter Numbers (1.5, 2.5)
# ==============================================================================

def test_non_integer_chapter_numbers(migrated_db: sqlite3.Connection):
    cursor = migrated_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Demo', 'demo') RETURNING id")
    m_id = cursor.fetchone()["id"]
    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'local', 'loc-1') RETURNING id",
        (m_id,),
    )
    s_id = cursor.fetchone()["id"]

    cursor.execute(
        "INSERT INTO chapters (manga_id, manga_source_id, chapter_number, title) VALUES (?, ?, 1.5, 'Special')",
        (m_id, s_id),
    )
    migrated_db.commit()

    cursor.execute("SELECT chapter_number FROM chapters WHERE manga_source_id = ?", (s_id,))
    val = cursor.fetchone()["chapter_number"]
    assert val == 1.5


# ==============================================================================
# 8. FTS5 Full-Text Search and Triggers
# ==============================================================================

def test_fts5_search_and_triggers(migrated_db: sqlite3.Connection):
    cursor = migrated_db.cursor()

    if not is_fts5_available(migrated_db):
        pytest.skip("FTS5 is not available in this SQLite build")

    # 1. Insert manga
    cursor.execute(
        """
        INSERT INTO manga (title, slug, original_title, description)
        VALUES ('Магическая Битва', 'magicheskaya-bitva', 'Jujutsu Kaisen', 'История о проклятиях и магах')
        """
    )
    migrated_db.commit()

    # 2. Search by Russian word in title
    results = search_manga(migrated_db, "Магическая")
    assert len(results) >= 1
    assert results[0]["slug"] == "magicheskaya-bitva"

    # 3. Search by original title
    results = search_manga(migrated_db, "Jujutsu")
    assert len(results) >= 1
    assert results[0]["slug"] == "magicheskaya-bitva"

    # 4. Search by description term
    results = search_manga(migrated_db, "проклятиях")
    assert len(results) >= 1

    # 5. Test UPDATE trigger sync
    cursor.execute(
        """
        UPDATE manga
        SET title = 'Клинок Рассекающий Демонов',
            original_title = 'Demon Slayer',
            description = 'Охотники на демонов'
        WHERE slug = 'magicheskaya-bitva'
        """
    )
    migrated_db.commit()

    # Old terms no longer match
    assert len(search_manga(migrated_db, "Jujutsu")) == 0
    assert len(search_manga(migrated_db, "Магическая")) == 0
    # New terms match
    results = search_manga(migrated_db, "Демонов")
    assert len(results) >= 1
    assert results[0]["title"] == "Клинок Рассекающий Демонов"
    results_en = search_manga(migrated_db, "Demon")
    assert len(results_en) >= 1

    # 6. Test DELETE trigger sync
    cursor.execute("DELETE FROM manga WHERE slug = 'magicheskaya-bitva'")
    migrated_db.commit()
    assert len(search_manga(migrated_db, "Демонов")) == 0


def test_fts5_fallback_to_like(migrated_db: sqlite3.Connection):
    """Test search_manga fallback if FTS table does not exist."""
    cursor = migrated_db.cursor()
    cursor.execute("INSERT INTO manga (title, slug, description) VALUES ('Врата Штейна', 'steins-gate', 'Путешествия во времени')")
    migrated_db.commit()

    # Drop FTS virtual table to simulate environment without FTS5
    cursor.execute("DROP TABLE IF EXISTS manga_search_index")
    migrated_db.commit()

    results = search_manga(migrated_db, "Штейна")
    assert len(results) == 1
    assert results[0]["slug"] == "steins-gate"


# ==============================================================================
# 9. Seed Service & Idempotency
# ==============================================================================

def test_seed_data_and_idempotency(migrated_db: sqlite3.Connection):
    """Seed data should populate fictional catalog, and repeated runs must not duplicate."""
    # First seed run
    seed_data(migrated_db)

    cursor = migrated_db.cursor()
    cursor.execute("SELECT COUNT(*) FROM manga")
    manga_count_1 = cursor.fetchone()[0]
    assert manga_count_1 == 4

    cursor.execute("SELECT COUNT(*) FROM genres")
    genre_count_1 = cursor.fetchone()[0]
    assert genre_count_1 >= 10

    cursor.execute("SELECT COUNT(*) FROM chapters")
    chapter_count_1 = cursor.fetchone()[0]
    assert chapter_count_1 >= 8

    cursor.execute("SELECT COUNT(*) FROM chapter_pages")
    page_count_1 = cursor.fetchone()[0]
    assert page_count_1 >= 20

    # Verify decimal chapter exists in seed
    cursor.execute("SELECT chapter_number, title FROM chapters WHERE chapter_number = 2.5")
    ch_2_5 = cursor.fetchone()
    assert ch_2_5 is not None
    assert "Кулинарная битва" in ch_2_5["title"]

    # Verify multi-source exists for 'onigiri-chronicles'
    cursor.execute(
        """
        SELECT ms.source_name, ms.source_manga_id
        FROM manga_sources ms
        JOIN manga m ON ms.manga_id = m.id
        WHERE m.slug = 'onigiri-chronicles'
        """
    )
    sources = cursor.fetchall()
    source_names = {s["source_name"] for s in sources}
    assert "mangadex" in source_names
    assert "local_seed" in source_names

    # Second seed run (Idempotency test)
    seed_data(migrated_db)

    cursor.execute("SELECT COUNT(*) FROM manga")
    assert cursor.fetchone()[0] == manga_count_1

    cursor.execute("SELECT COUNT(*) FROM genres")
    assert cursor.fetchone()[0] == genre_count_1

    cursor.execute("SELECT COUNT(*) FROM chapters")
    assert cursor.fetchone()[0] == chapter_count_1

    cursor.execute("SELECT COUNT(*) FROM chapter_pages")
    assert cursor.fetchone()[0] == page_count_1


# ==============================================================================
# 10. Domain Models and Pydantic Schemas
# ==============================================================================

def test_domain_models_and_schemas(migrated_db: sqlite3.Connection):
    seed_data(migrated_db)
    cursor = migrated_db.cursor()

    # Load manga row
    cursor.execute("SELECT * FROM manga WHERE slug = 'onigiri-chronicles'")
    row = cursor.fetchone()

    # Test Domain Model from_row and to_dict
    manga_domain = Manga.from_row(row)
    assert manga_domain.slug == "onigiri-chronicles"
    assert manga_domain.rating == 9.2
    assert isinstance(manga_domain.to_dict(), dict)

    # Test Pydantic validation and serialization
    manga_list_schema = MangaListRead(
        id=manga_domain.id,
        title=manga_domain.title,
        slug=manga_domain.slug,
        status=manga_domain.status,
        type=manga_domain.type,
        rating=manga_domain.rating,
        views_count=manga_domain.views_count,
        genres=[GenreRead(id=1, name="Сёнэн", slug="shonen")],
        authors=[AuthorRead(id=1, name="Kenji Sato", role="author")],
    )
    assert manga_list_schema.title == "Хроники Онигири"
    assert manga_list_schema.genres[0].slug == "shonen"

    # Test MangaDetailRead
    manga_detail = MangaDetailRead(
        id=manga_domain.id,
        title=manga_domain.title,
        slug=manga_domain.slug,
        status=manga_domain.status,
        type=manga_domain.type,
        rating=manga_domain.rating,
        views_count=manga_domain.views_count,
        description=manga_domain.description,
        sources=[
            MangaSourceRead(
                id=1,
                manga_id=manga_domain.id,
                source_name="mangadex",
                source_manga_id="md-onigiri-001",
            )
        ],
        chapters=[
            ChapterRead(
                id=1,
                manga_id=manga_domain.id,
                manga_source_id=1,
                chapter_number=2.5,
                title="Bonus",
            )
        ],
    )
    assert manga_detail.sources[0].source_name == "mangadex"
    assert manga_detail.chapters[0].chapter_number == 2.5


# ==============================================================================
# 11. Transactionality & Full Rollback on Migration Failure (ISS-02)
# ==============================================================================

def test_migration_transaction_rollback_on_failure(tmp_path: Path):
    """
    Ensure that when a migration fails, all DDL (tables, indexes, triggers)
    and DML statements are completely rolled back, and version is not recorded.
    """
    from database import migrations

    db_file = tmp_path / "rollback_test.db"
    conn = get_connection(db_file)

    def failing_migration(connection: sqlite3.Connection):
        connection.execute("CREATE TABLE deliberate_table (id INTEGER PRIMARY KEY, note TEXT)")
        connection.execute("CREATE INDEX idx_deliberate ON deliberate_table(note)")
        connection.execute(
            """
            CREATE TRIGGER trg_deliberate AFTER INSERT ON deliberate_table
            BEGIN
                SELECT 1;
            END;
            """
        )
        # Deliberately raise an unhandled exception midway
        raise RuntimeError("Simulated failure in migration execution")

    # Temporarily append faulty migration to MIGRATIONS
    faulty_version = 999
    original_migrations = list(migrations.MIGRATIONS)
    migrations.MIGRATIONS.append((faulty_version, "999_failing_migration", failing_migration))

    try:
        with pytest.raises(RuntimeError, match="Simulated failure"):
            run_migrations(conn)

        cursor = conn.cursor()

        # 1. Verify deliberate_table was rolled back and does not exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='deliberate_table'")
        assert cursor.fetchone() is None

        # 2. Verify idx_deliberate does not exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_deliberate'")
        assert cursor.fetchone() is None

        # 3. Verify trg_deliberate does not exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name='trg_deliberate'")
        assert cursor.fetchone() is None

        # 4. Verify version was NOT recorded in schema_migrations
        cursor.execute("SELECT version FROM schema_migrations WHERE version = ?", (faulty_version,))
        assert cursor.fetchone() is None

    finally:
        migrations.MIGRATIONS = original_migrations
        conn.close()


def test_migration_recovery_after_simulated_fault(tmp_path: Path):
    """
    Ensure the database can recover and successfully apply migrations
    after a previously failed migration attempt.
    """
    from database import migrations

    db_file = tmp_path / "recovery_test.db"
    conn = get_connection(db_file)

    step = {"should_fail": True}

    def intermittent_migration(connection: sqlite3.Connection):
        connection.execute("CREATE TABLE recovered_table (id INTEGER PRIMARY KEY, title TEXT)")
        if step["should_fail"]:
            raise RuntimeError("Temporary migration failure")

    test_version = 888
    original_migrations = list(migrations.MIGRATIONS)
    migrations.MIGRATIONS.append((test_version, "888_intermittent_migration", intermittent_migration))

    try:
        # First attempt: fails
        with pytest.raises(RuntimeError):
            run_migrations(conn)

        # Assert table does not exist
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='recovered_table'")
        assert cur.fetchone() is None

        # Fix the issue: second attempt succeeds
        step["should_fail"] = False
        run_migrations(conn)

        # Assert table now exists and version is registered
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='recovered_table'")
        assert cur.fetchone() is not None
        cur.execute("SELECT version FROM schema_migrations WHERE version = ?", (test_version,))
        assert cur.fetchone() is not None

        # Idempotency check: rerun once more
        run_migrations(conn)

    finally:
        migrations.MIGRATIONS = original_migrations
        conn.close()


# ==============================================================================
# 12. Manga Sources Integrity & Cannot Update manga_id (ISS-01)
# ==============================================================================

def test_manga_sources_manga_id_cannot_be_updated_when_chapters_exist(migrated_db: sqlite3.Connection):
    """
    Ensure manga_sources.manga_id cannot be reassigned to another manga
    when chapters are already associated with this source.
    """
    cursor = migrated_db.cursor()

    # 1. Create two manga
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Manga 1', 'manga-1') RETURNING id")
    m1_id = cursor.fetchone()["id"]
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Manga 2', 'manga-2') RETURNING id")
    m2_id = cursor.fetchone()["id"]

    # 2. Create source for Manga 1
    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'src1', 's1') RETURNING id",
        (m1_id,),
    )
    src_id = cursor.fetchone()["id"]

    # 3. Create chapter for this source
    cursor.execute(
        "INSERT INTO chapters (manga_id, manga_source_id, chapter_number, title) VALUES (?, ?, 1.0, 'Ch 1')",
        (m1_id, src_id),
    )
    migrated_db.commit()

    # 4. Attempt to update manga_sources.manga_id = m2_id while chapter exists -> Must FAIL
    with pytest.raises(sqlite3.IntegrityError, match="Cannot update manga_id"):
        cursor.execute("UPDATE manga_sources SET manga_id = ? WHERE id = ?", (m2_id, src_id))

    # Verify original manga_id remains unchanged
    cursor.execute("SELECT manga_id FROM manga_sources WHERE id = ?", (src_id,))
    assert cursor.fetchone()["manga_id"] == m1_id

    # 5. Remove chapter, then update manga_id -> Must SUCCEED
    cursor.execute("DELETE FROM chapters WHERE manga_source_id = ?", (src_id,))
    migrated_db.commit()

    cursor.execute("UPDATE manga_sources SET manga_id = ? WHERE id = ?", (m2_id, src_id))
    migrated_db.commit()

    cursor.execute("SELECT manga_id FROM manga_sources WHERE id = ?", (src_id,))
    assert cursor.fetchone()["manga_id"] == m2_id


# ==============================================================================
# 13. Global Uniqueness of External Sources (ISS-03)
# ==============================================================================

def test_manga_sources_global_uniqueness(migrated_db: sqlite3.Connection):
    """
    Ensure the same external (source_name, source_manga_id) cannot be linked
    to two different manga.
    """
    cursor = migrated_db.cursor()

    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Manga A', 'manga-a') RETURNING id")
    m_a_id = cursor.fetchone()["id"]
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Manga B', 'manga-b') RETURNING id")
    m_b_id = cursor.fetchone()["id"]

    # Insert source for Manga A
    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangadex', 'md-unique-123')",
        (m_a_id,),
    )
    migrated_db.commit()

    # Attempt to insert same source for Manga B -> Must FAIL
    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute(
            "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'mangadex', 'md-unique-123')",
            (m_b_id,),
        )


# ==============================================================================
# 14. Cascade Deletion Tests (ISS-04)
# ==============================================================================

def test_cascade_deletion_manga(migrated_db: sqlite3.Connection):
    """
    Deleting a manga must cascade delete related sources, chapters, pages,
    manga_authors, and manga_genres, but must preserve global authors and genres.
    """
    cursor = migrated_db.cursor()

    # 1. Setup entities
    cursor.execute("INSERT INTO authors (name) VALUES ('Test Author') RETURNING id")
    author_id = cursor.fetchone()["id"]
    cursor.execute("INSERT INTO genres (name, slug) VALUES ('Test Genre', 'test-genre') RETURNING id")
    genre_id = cursor.fetchone()["id"]

    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Cascade Manga', 'cascade-manga') RETURNING id")
    manga_id = cursor.fetchone()["id"]

    cursor.execute("INSERT INTO manga_authors (manga_id, author_id) VALUES (?, ?)", (manga_id, author_id))
    cursor.execute("INSERT INTO manga_genres (manga_id, genre_id) VALUES (?, ?)", (manga_id, genre_id))

    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'src_casc', 'sc-1') RETURNING id",
        (manga_id,),
    )
    src_id = cursor.fetchone()["id"]

    cursor.execute(
        "INSERT INTO chapters (manga_id, manga_source_id, chapter_number) VALUES (?, ?, 1.0) RETURNING id",
        (manga_id, src_id),
    )
    chapter_id = cursor.fetchone()["id"]

    cursor.execute("INSERT INTO chapter_pages (chapter_id, page_number, image_url) VALUES (?, 1, 'http://p1.png')", (chapter_id,))
    migrated_db.commit()

    # 2. Delete the manga
    cursor.execute("DELETE FROM manga WHERE id = ?", (manga_id,))
    migrated_db.commit()

    # 3. Assert all child links/records are deleted
    assert cursor.execute("SELECT COUNT(*) FROM manga_sources WHERE manga_id = ?", (manga_id,)).fetchone()[0] == 0
    assert cursor.execute("SELECT COUNT(*) FROM chapters WHERE manga_id = ?", (manga_id,)).fetchone()[0] == 0
    assert cursor.execute("SELECT COUNT(*) FROM chapter_pages WHERE chapter_id = ?", (chapter_id,)).fetchone()[0] == 0
    assert cursor.execute("SELECT COUNT(*) FROM manga_authors WHERE manga_id = ?", (manga_id,)).fetchone()[0] == 0
    assert cursor.execute("SELECT COUNT(*) FROM manga_genres WHERE manga_id = ?", (manga_id,)).fetchone()[0] == 0

    # 4. Assert master entities still exist
    assert cursor.execute("SELECT COUNT(*) FROM authors WHERE id = ?", (author_id,)).fetchone()[0] == 1
    assert cursor.execute("SELECT COUNT(*) FROM genres WHERE id = ?", (genre_id,)).fetchone()[0] == 1


def test_cascade_deletion_manga_sources(migrated_db: sqlite3.Connection):
    """
    Deleting a manga_source must cascade delete chapters and pages,
    while keeping the parent manga intact.
    """
    cursor = migrated_db.cursor()

    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Source Cascade', 'src-cascade') RETURNING id")
    manga_id = cursor.fetchone()["id"]

    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (?, 'src_del', 'sd-1') RETURNING id",
        (manga_id,),
    )
    src_id = cursor.fetchone()["id"]

    cursor.execute(
        "INSERT INTO chapters (manga_id, manga_source_id, chapter_number) VALUES (?, ?, 1.0) RETURNING id",
        (manga_id, src_id),
    )
    chapter_id = cursor.fetchone()["id"]

    cursor.execute("INSERT INTO chapter_pages (chapter_id, page_number, image_url) VALUES (?, 1, 'http://p1.png')", (chapter_id,))
    migrated_db.commit()

    # Delete source
    cursor.execute("DELETE FROM manga_sources WHERE id = ?", (src_id,))
    migrated_db.commit()

    # Chapters and pages deleted
    assert cursor.execute("SELECT COUNT(*) FROM chapters WHERE id = ?", (chapter_id,)).fetchone()[0] == 0
    assert cursor.execute("SELECT COUNT(*) FROM chapter_pages WHERE chapter_id = ?", (chapter_id,)).fetchone()[0] == 0

    # Parent manga remains
    assert cursor.execute("SELECT COUNT(*) FROM manga WHERE id = ?", (manga_id,)).fetchone()[0] == 1


# ==============================================================================
# 15. Migration 4 & Schema Compatibility Regression Tests (TASK 007.3)
# ==============================================================================

def test_migration_004_upgrades_task_007_database(tmp_path: Path):
    """
    Verify that an existing database created under TASK 007 (with versions 1, 2, 3
    and old UNIQUE(manga_id, source_name, source_manga_id)) is safely upgraded
    by Migration 4 to global UNIQUE(source_name, source_manga_id) with all IDs,
    chapters, pages, and foreign keys intact.
    """
    db_file = tmp_path / "task007_legacy.db"
    conn = get_connection(db_file)
    cursor = conn.cursor()

    # 1. Setup exact TASK 007 state: versions 1, 2, 3 applied
    cursor.execute(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute("INSERT INTO schema_migrations VALUES (1, '001_initial_catalog_schema', CURRENT_TIMESTAMP)")
    cursor.execute("INSERT INTO schema_migrations VALUES (2, '002_sources_authors_genres_chapters', CURRENT_TIMESTAMP)")
    cursor.execute("INSERT INTO schema_migrations VALUES (3, '003_fts5_search_index', CURRENT_TIMESTAMP)")

    cursor.execute(
        """
        CREATE TABLE manga (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            slug TEXT UNIQUE,
            original_title TEXT,
            description TEXT,
            cover_url TEXT,
            banner_url TEXT,
            status TEXT NOT NULL DEFAULT 'ongoing',
            type TEXT NOT NULL DEFAULT 'manga',
            release_year INTEGER,
            rating REAL NOT NULL DEFAULT 0.0,
            views_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Legacy manga_sources with composite UNIQUE including manga_id
    cursor.execute(
        """
        CREATE TABLE manga_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manga_id INTEGER NOT NULL REFERENCES manga(id) ON DELETE CASCADE,
            source_name TEXT NOT NULL,
            source_manga_id TEXT NOT NULL,
            source_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(manga_id, source_name, source_manga_id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manga_id INTEGER NOT NULL REFERENCES manga(id) ON DELETE CASCADE,
            manga_source_id INTEGER NOT NULL REFERENCES manga_sources(id) ON DELETE CASCADE,
            chapter_number REAL NOT NULL,
            volume_number INTEGER,
            title TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(manga_source_id, chapter_number)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE chapter_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL,
            image_url TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(chapter_id, page_number)
        )
        """
    )

    # Insert existing rows
    cursor.execute("INSERT INTO manga (id, title, slug) VALUES (10, 'Legacy Manga', 'legacy-manga')")
    cursor.execute("INSERT INTO manga (id, title, slug) VALUES (20, 'Second Manga', 'second-manga')")
    cursor.execute(
        "INSERT INTO manga_sources (id, manga_id, source_name, source_manga_id, source_url) VALUES (50, 10, 'mangadex', 'md-leg-50', 'http://leg50')",
    )
    cursor.execute(
        "INSERT INTO chapters (id, manga_id, manga_source_id, chapter_number, title) VALUES (500, 10, 50, 1.5, 'Chapter 1.5')",
    )
    cursor.execute(
        "INSERT INTO chapter_pages (id, chapter_id, page_number, image_url) VALUES (5000, 500, 1, 'http://p1.jpg')",
    )
    conn.commit()

    # 2. Run migrations (Migration 4 will apply)
    run_migrations(conn)

    # 3. Assert Migration 4 recorded in schema_migrations
    cursor.execute("SELECT version FROM schema_migrations WHERE version = 4")
    assert cursor.fetchone() is not None

    # 4. Assert source row preserved exactly with same ID
    cursor.execute("SELECT * FROM manga_sources WHERE id = 50")
    source_row = cursor.fetchone()
    assert source_row is not None
    assert source_row["manga_id"] == 10
    assert source_row["source_manga_id"] == "md-leg-50"

    # 5. Assert chapter and page relations preserved
    cursor.execute("SELECT * FROM chapters WHERE id = 500")
    ch_row = cursor.fetchone()
    assert ch_row is not None
    assert ch_row["manga_source_id"] == 50
    assert ch_row["chapter_number"] == 1.5

    cursor.execute("SELECT * FROM chapter_pages WHERE id = 5000")
    pg_row = cursor.fetchone()
    assert pg_row is not None
    assert pg_row["chapter_id"] == 500

    # 6. Assert foreign keys are 100% valid
    cursor.execute("PRAGMA foreign_key_check")
    assert cursor.fetchall() == []

    # 7. Assert duplicate external source on different manga is now forbidden
    with pytest.raises(sqlite3.IntegrityError):
        cursor.execute(
            "INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (20, 'mangadex', 'md-leg-50')",
        )

    # 8. Assert trigger prevents updating manga_id when chapters exist
    with pytest.raises(sqlite3.IntegrityError, match="Cannot update manga_id"):
        cursor.execute("UPDATE manga_sources SET manga_id = 20 WHERE id = 50")

    # 9. Assert idempotency on second run
    run_migrations(conn)
    cursor.execute("SELECT COUNT(*) FROM schema_migrations")
    assert cursor.fetchone()[0] == 5

    conn.close()


def test_migration_004_aborts_safely_on_conflicting_duplicates(tmp_path: Path):
    """
    If existing database already has conflicting duplicates of (source_name, source_manga_id),
    Migration 4 must fail with IntegrityError and rollback cleanly without altering data.
    """
    db_file = tmp_path / "conflict_legacy.db"
    conn = get_connection(db_file)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute("INSERT INTO schema_migrations VALUES (1, '001', CURRENT_TIMESTAMP)")
    cursor.execute("INSERT INTO schema_migrations VALUES (2, '002', CURRENT_TIMESTAMP)")
    cursor.execute("INSERT INTO schema_migrations VALUES (3, '003', CURRENT_TIMESTAMP)")

    cursor.execute("CREATE TABLE manga (id INTEGER PRIMARY KEY, title TEXT, slug TEXT UNIQUE)")
    cursor.execute(
        """
        CREATE TABLE manga_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manga_id INTEGER NOT NULL REFERENCES manga(id),
            source_name TEXT NOT NULL,
            source_manga_id TEXT NOT NULL,
            source_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(manga_id, source_name, source_manga_id)
        )
        """
    )
    cursor.execute("INSERT INTO manga VALUES (1, 'M1', 'm1')")
    cursor.execute("INSERT INTO manga VALUES (2, 'M2', 'm2')")
    # Deliberate conflict across two manga
    cursor.execute("INSERT INTO manga_sources (id, manga_id, source_name, source_manga_id) VALUES (1, 1, 'mangadex', 'md-shared')")
    cursor.execute("INSERT INTO manga_sources (id, manga_id, source_name, source_manga_id) VALUES (2, 2, 'mangadex', 'md-shared')")
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="duplicate external sources found"):
        run_migrations(conn)

    # Verify both records still exist unchanged
    cursor.execute("SELECT COUNT(*) FROM manga_sources")
    assert cursor.fetchone()[0] == 2

    # Verify version 4 was NOT registered
    cursor.execute("SELECT version FROM schema_migrations WHERE version = 4")
    assert cursor.fetchone() is None

    conn.close()


def test_seed_detects_conflict_on_foreign_manga(migrated_db: sqlite3.Connection):
    """
    seed_data must detect and reject any external source conflict if an ID
    already belongs to another manga, rather than silently overwriting or ignoring it.
    """
    seed_data(migrated_db)

    # Attempt to seed a fake manga reusing onigiri's source ID 'md-onigiri-001'
    conflicting_manga_data = [
        {
            "title": "Conflicting Manga",
            "slug": "conflicting-manga",
            "original_title": "Conflict",
            "description": "Conflict description",
            "cover_url": None,
            "banner_url": None,
            "status": "ongoing",
            "type": "manga",
            "release_year": 2024,
            "rating": 5.0,
            "views_count": 100,
            "genres": [],
            "authors": [],
            "sources": [
                {
                    "source_name": "mangadex",
                    "source_manga_id": "md-onigiri-001",  # Belongs to onigiri-chronicles!
                    "source_url": "http://conflict.com",
                    "chapters": [],
                }
            ],
        }
    ]

    from services import seed
    original_sample = seed.SAMPLE_MANGA
    seed.SAMPLE_MANGA = conflicting_manga_data

    try:
        with pytest.raises(ValueError, match="Seed conflict: external source"):
            seed_data(migrated_db)
    finally:
        seed.SAMPLE_MANGA = original_sample


# ==============================================================================
# 16. Nested Transaction Safety & Outer Transaction Protection (TASK 007.4)
# ==============================================================================

def test_migration_004_rejects_run_inside_outer_transaction_to_prevent_fk_cascade(tmp_path: Path):
    """
    Ensure that if a caller invokes run_migrations inside an active outer transaction,
    Migration 4 safely aborts before modifying any data because SQLite prohibits
    disabling PRAGMA foreign_keys inside an open transaction.
    Chapters, pages, and outer transaction must be 100% preserved.
    """
    db_file = tmp_path / "nested_tx_test.db"
    conn = get_connection(db_file)
    cursor = conn.cursor()

    # 1. Setup exact TASK 007 state: versions 1, 2, 3 applied
    cursor.execute(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute("INSERT INTO schema_migrations VALUES (1, '001', CURRENT_TIMESTAMP)")
    cursor.execute("INSERT INTO schema_migrations VALUES (2, '002', CURRENT_TIMESTAMP)")
    cursor.execute("INSERT INTO schema_migrations VALUES (3, '003', CURRENT_TIMESTAMP)")

    cursor.execute("CREATE TABLE manga (id INTEGER PRIMARY KEY, title TEXT, slug TEXT UNIQUE)")
    cursor.execute(
        """
        CREATE TABLE manga_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manga_id INTEGER NOT NULL REFERENCES manga(id) ON DELETE CASCADE,
            source_name TEXT NOT NULL,
            source_manga_id TEXT NOT NULL,
            source_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(manga_id, source_name, source_manga_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manga_id INTEGER NOT NULL REFERENCES manga(id) ON DELETE CASCADE,
            manga_source_id INTEGER NOT NULL REFERENCES manga_sources(id) ON DELETE CASCADE,
            chapter_number REAL NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE chapter_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL,
            image_url TEXT NOT NULL
        )
        """
    )

    cursor.execute("INSERT INTO manga VALUES (10, 'Manga 10', 'm-10')")
    cursor.execute("INSERT INTO manga_sources VALUES (50, 10, 'mangadex', 'md-50', 'http://url', '2026', '2026')")
    cursor.execute("INSERT INTO chapters VALUES (500, 10, 50, 1.0)")
    cursor.execute("INSERT INTO chapter_pages VALUES (5000, 500, 1, 'http://p1')")
    conn.commit()

    # Verify foreign_keys is ON
    assert bool(cursor.execute("PRAGMA foreign_keys").fetchone()[0]) is True

    # 2. Caller opens outer transaction
    conn.execute("BEGIN IMMEDIATE")
    assert conn.in_transaction is True

    # 3. Invoking run_migrations must safely reject table alteration
    with pytest.raises(sqlite3.OperationalError, match="Cannot execute migration 4 inside an active transaction"):
        run_migrations(conn)

    # 4. Verify chapters and pages were NOT deleted
    cursor.execute("SELECT COUNT(*) FROM chapters WHERE id = 500")
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM chapter_pages WHERE id = 5000")
    assert cursor.fetchone()[0] == 1

    # 5. Verify outer transaction remains active and manageable by caller
    assert conn.in_transaction is True
    conn.execute("INSERT INTO manga VALUES (99, 'Caller Manga', 'caller-manga')")
    conn.commit()

    # 6. Verify foreign_keys setting is still ON
    assert bool(cursor.execute("PRAGMA foreign_keys").fetchone()[0]) is True

    # 7. Now run run_migrations without active outer transaction -> Must SUCCEED cleanly
    run_migrations(conn)

    # Migration 4 applied
    cursor.execute("SELECT version FROM schema_migrations WHERE version = 4")
    assert cursor.fetchone() is not None

    # Chapters and pages still intact
    cursor.execute("SELECT COUNT(*) FROM chapters WHERE id = 500")
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM chapter_pages WHERE id = 5000")
    assert cursor.fetchone()[0] == 1

    # foreign_key_check is completely clean
    cursor.execute("PRAGMA foreign_key_check")
    assert cursor.fetchall() == []

    conn.close()


def test_savepoint_rollback_on_migration_fault_preserves_outer_transaction(tmp_path: Path):
    """
    Ensure that when a migration fails inside a SAVEPOINT (nested in caller's tx),
    the SAVEPOINT rolls back, data is preserved, and caller's outer transaction
    remains active and intact.
    """
    from database import migrations

    db_file = tmp_path / "savepoint_test.db"
    conn = get_connection(db_file)
    cursor = conn.cursor()

    # First run base migrations so DB is up to date
    run_migrations(conn)

    # Start outer transaction
    conn.execute("BEGIN IMMEDIATE")
    cursor.execute("INSERT INTO manga (title, slug) VALUES ('Outer Manga', 'outer-manga')")

    def failing_migration(connection: sqlite3.Connection):
        connection.execute("CREATE TABLE sp_fault_table (id INTEGER PRIMARY KEY)")
        raise RuntimeError("Deliberate fault in savepoint")

    fault_version = 777
    orig = list(migrations.MIGRATIONS)
    migrations.MIGRATIONS.append((fault_version, "777_fault", failing_migration))

    try:
        with pytest.raises(RuntimeError, match="Deliberate fault"):
            run_migrations(conn)

        # 1. Faulty table was rolled back
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sp_fault_table'")
        assert cursor.fetchone() is None

        # 2. Version was not recorded
        cursor.execute("SELECT version FROM schema_migrations WHERE version = ?", (fault_version,))
        assert cursor.fetchone() is None

        # 3. Caller's outer transaction is still active and can be committed
        assert conn.in_transaction is True
        conn.commit()

        # 4. Caller's data was committed successfully
        cursor.execute("SELECT title FROM manga WHERE slug = 'outer-manga'")
        assert cursor.fetchone()[0] == "Outer Manga"

    finally:
        migrations.MIGRATIONS = orig
        conn.close()
