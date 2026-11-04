"""
Comprehensive tests for SQLite data layer, migrations, integrity triggers,
FTS5 full-text search, domain models, Pydantic schemas and seed data.
"""

import sqlite3
import pytest
from pathlib import Path

from database.connection import get_connection, init_db
from database.migrations import (
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
    assert cursor.fetchone()[0] == 3


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
