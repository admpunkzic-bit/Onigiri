"""
Database migration management and schema versioning for SQLite.
Ensures safe, idempotent migrations preserving existing data.
"""

import logging
import re
import sqlite3
from typing import Callable, List, Tuple

logger = logging.getLogger(__name__)

# Transliteration dictionary for Russian Cyrillic to Latin for slug generation
_CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slugify(text: str) -> str:
    """Generate a clean URL-friendly slug from text (supporting Cyrillic and Latin)."""
    text = text.lower().strip()
    result = []
    for char in text:
        if char in _CYRILLIC_TO_LATIN:
            result.append(_CYRILLIC_TO_LATIN[char])
        elif char.isalnum():
            result.append(char)
        elif char in (" ", "-", "_"):
            result.append("-")
    slug = "".join(result)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "item"


def is_fts5_available(conn: sqlite3.Connection) -> bool:
    """Check if the SQLite engine supports FTS5 virtual tables."""
    try:
        cursor = conn.cursor()
        cursor.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_test USING fts5(x);")
        cursor.execute("DROP TABLE IF EXISTS _fts5_test;")
        return True
    except sqlite3.OperationalError:
        return False


def _migration_001_initial_catalog_schema(conn: sqlite3.Connection) -> None:
    """
    Migration 1: Ensure manga table exists and has all required catalog columns.
    Safely migrates legacy schema (id, title, description, cover_url, created_at)
    without data loss.
    """
    cursor = conn.cursor()

    # Check if manga table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='manga'")
    table_exists = cursor.fetchone() is not None

    if not table_exists:
        # Create full manga table from scratch
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
    else:
        # Table exists: inspect existing columns and add missing ones
        cursor.execute("PRAGMA table_info(manga)")
        existing_cols = {row["name"] for row in cursor.fetchall()}

        # Note: SQLite ALTER TABLE ADD COLUMN does NOT allow non-constant expressions
        # such as CURRENT_TIMESTAMP in DEFAULT clauses.
        columns_to_add = [
            ("slug", "TEXT"),
            ("original_title", "TEXT"),
            ("banner_url", "TEXT"),
            ("status", "TEXT NOT NULL DEFAULT 'ongoing'"),
            ("type", "TEXT NOT NULL DEFAULT 'manga'"),
            ("release_year", "INTEGER"),
            ("rating", "REAL NOT NULL DEFAULT 0.0"),
            ("views_count", "INTEGER NOT NULL DEFAULT 0"),
            ("updated_at", "TIMESTAMP"),
        ]

        for col_name, col_def in columns_to_add:
            if col_name not in existing_cols:
                cursor.execute(f"ALTER TABLE manga ADD COLUMN {col_name} {col_def}")
                logger.info(f"Added column manga.{col_name}")

        # Ensure updated_at is populated for existing rows
        cursor.execute("UPDATE manga SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")

        # Populate slug for any existing rows that have NULL or empty slug
        cursor.execute("SELECT id, title, slug FROM manga WHERE slug IS NULL OR slug = ''")
        rows_needing_slug = cursor.fetchall()
        for row in rows_needing_slug:
            base_slug = slugify(row["title"]) or f"manga-{row['id']}"
            unique_slug = base_slug
            counter = 1
            while True:
                cursor.execute("SELECT id FROM manga WHERE slug = ? AND id != ?", (unique_slug, row["id"]))
                if not cursor.fetchone():
                    break
                counter += 1
                unique_slug = f"{base_slug}-{counter}"

            cursor.execute("UPDATE manga SET slug = ? WHERE id = ?", (unique_slug, row["id"]))
            logger.info(f"Populated slug for manga id={row['id']}: '{unique_slug}'")

    # Trigger to auto-generate fallback slug if not provided on insert
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_manga_auto_slug
        AFTER INSERT ON manga
        FOR EACH ROW
        WHEN NEW.slug IS NULL OR NEW.slug = ''
        BEGIN
            UPDATE manga SET slug = 'manga-' || NEW.id WHERE id = NEW.id;
        END;
        """
    )

    # Unique index on slug
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_manga_slug ON manga(slug)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_manga_rating ON manga(rating DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_manga_views ON manga(views_count DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_manga_updated_at ON manga(updated_at DESC)")


def _migration_002_sources_authors_genres_chapters(conn: sqlite3.Connection) -> None:
    """
    Migration 2: Create manga_sources, authors, manga_authors, genres, manga_genres,
    chapters, chapter_pages and data integrity triggers.
    """
    cursor = conn.cursor()

    # 1. manga_sources (Multiple external sources per manga)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS manga_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manga_id INTEGER NOT NULL REFERENCES manga(id) ON DELETE CASCADE,
            source_name TEXT NOT NULL,
            source_manga_id TEXT NOT NULL,
            source_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_name, source_manga_id)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_manga_sources_manga_id ON manga_sources(manga_id)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_manga_sources_lookup ON manga_sources(source_name, source_manga_id)")

    # 2. authors
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS authors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # 3. manga_authors (M2M relation with role)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS manga_authors (
            manga_id INTEGER NOT NULL REFERENCES manga(id) ON DELETE CASCADE,
            author_id INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
            role TEXT NOT NULL DEFAULT 'author',
            PRIMARY KEY (manga_id, author_id, role)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_manga_authors_author_id ON manga_authors(author_id)")

    # 4. genres
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS genres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            slug TEXT NOT NULL UNIQUE
        )
        """
    )

    # 5. manga_genres (M2M relation)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS manga_genres (
            manga_id INTEGER NOT NULL REFERENCES manga(id) ON DELETE CASCADE,
            genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE CASCADE,
            PRIMARY KEY (manga_id, genre_id)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_manga_genres_genre_id ON manga_genres(genre_id)")

    # 6. chapters (Supports non-integer chapter numbers such as 1.5)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS chapters (
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
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chapters_manga_source ON chapters(manga_source_id, chapter_number)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chapters_manga_id ON chapters(manga_id)")

    # 7. chapter_pages
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS chapter_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL,
            image_url TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(chapter_id, page_number)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chapter_pages_chapter ON chapter_pages(chapter_id, page_number)")

    # 8. Data integrity triggers:
    # Ensure chapters.manga_id matches manga_sources.manga_id for the given manga_source_id
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_chapters_manga_id_insert
        BEFORE INSERT ON chapters
        FOR EACH ROW
        WHEN (SELECT manga_id FROM manga_sources WHERE id = NEW.manga_source_id) != NEW.manga_id
        BEGIN
            SELECT RAISE(ABORT, 'Foreign key mismatch: chapter manga_id does not match manga_sources.manga_id');
        END;
        """
    )

    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_chapters_manga_id_update
        BEFORE UPDATE OF manga_id, manga_source_id ON chapters
        FOR EACH ROW
        WHEN (SELECT manga_id FROM manga_sources WHERE id = NEW.manga_source_id) != NEW.manga_id
        BEGIN
            SELECT RAISE(ABORT, 'Foreign key mismatch: chapter manga_id does not match manga_sources.manga_id');
        END;
        """
    )

    # Prevent updating manga_sources.manga_id if chapters already exist for this source
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_manga_sources_manga_id_update
        BEFORE UPDATE OF manga_id ON manga_sources
        FOR EACH ROW
        WHEN NEW.manga_id != OLD.manga_id AND (SELECT COUNT(*) FROM chapters WHERE manga_source_id = OLD.id) > 0
        BEGIN
            SELECT RAISE(ABORT, 'Cannot update manga_id: source already has associated chapters');
        END;
        """
    )


def _migration_003_fts5_search_index(conn: sqlite3.Connection) -> None:
    """
    Migration 3: Setup FTS5 full-text search index and automatic synchronization triggers.
    If FTS5 is not available in SQLite runtime, gracefully skips virtual table creation.
    """
    cursor = conn.cursor()

    if not is_fts5_available(conn):
        logger.warning("FTS5 is not supported by current SQLite build. Full-text search will fallback to LIKE.")
        return

    # Create FTS5 virtual table
    cursor.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS manga_search_index USING fts5(
            manga_id UNINDEXED,
            title,
            original_title,
            description,
            tokenize='unicode61'
        )
        """
    )

    # Trigger: Sync on INSERT
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_manga_fts_insert
        AFTER INSERT ON manga
        BEGIN
            INSERT INTO manga_search_index(manga_id, title, original_title, description)
            VALUES (NEW.id, NEW.title, COALESCE(NEW.original_title, ''), COALESCE(NEW.description, ''));
        END;
        """
    )

    # Trigger: Sync on UPDATE
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_manga_fts_update
        AFTER UPDATE OF title, original_title, description ON manga
        BEGIN
            DELETE FROM manga_search_index WHERE manga_id = OLD.id;
            INSERT INTO manga_search_index(manga_id, title, original_title, description)
            VALUES (NEW.id, NEW.title, COALESCE(NEW.original_title, ''), COALESCE(NEW.description, ''));
        END;
        """
    )

    # Trigger: Sync on DELETE
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_manga_fts_delete
        AFTER DELETE ON manga
        BEGIN
            DELETE FROM manga_search_index WHERE manga_id = OLD.id;
        END;
        """
    )

    # Populate index with any existing manga not yet in the index
    cursor.execute(
        """
        INSERT INTO manga_search_index(manga_id, title, original_title, description)
        SELECT id, title, COALESCE(original_title, ''), COALESCE(description, '')
        FROM manga
        WHERE id NOT IN (SELECT manga_id FROM manga_search_index)
        """
    )


def _migration_004_manga_sources_global_unique(conn: sqlite3.Connection) -> None:
    """
    Migration 4: Ensure global uniqueness of (source_name, source_manga_id) in manga_sources
    and install integrity triggers.
    Safely upgrades existing databases created by TASK 007 without data loss or foreign key breakages.
    If conflicting duplicate records exist, aborts with IntegrityError for manual resolution.
    """
    cursor = conn.cursor()

    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='manga_sources'")
    row = cursor.fetchone()
    if not row:
        return
    table_sql = row[0]

    norm_sql = re.sub(r"\s+", " ", table_sql)
    needs_alter = (
        "UNIQUE(source_name, source_manga_id)" not in norm_sql
        and "UNIQUE (source_name, source_manga_id)" not in norm_sql
    )

    if needs_alter:
        # Check if foreign keys are currently active and cannot be disabled due to an outer transaction
        is_fk_active = bool(cursor.execute("PRAGMA foreign_keys").fetchone()[0])
        if is_fk_active:
            raise sqlite3.OperationalError(
                "Cannot execute migration 4 inside an active transaction: altering table "
                "'manga_sources' requires disabling foreign keys (PRAGMA foreign_keys = OFF), "
                "which SQLite prohibits within an active transaction. "
                "Commit or rollback the outer transaction before executing migrations."
            )

        # Check for conflicting duplicates
        cursor.execute(
            """
            SELECT source_name, source_manga_id, COUNT(*) as cnt
            FROM manga_sources
            GROUP BY source_name, source_manga_id
            HAVING cnt > 1
            """
        )
        duplicates = cursor.fetchall()
        if duplicates:
            dup_details = [(d[0], d[1], d[2]) for d in duplicates]
            raise sqlite3.IntegrityError(
                f"Cannot apply migration 4: duplicate external sources found: {dup_details}. "
                "Manual resolution required."
            )

        # Recreate table safely without foreign key cascade to chapters
        cursor.execute(
            """
            CREATE TABLE manga_sources_v4 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                manga_id INTEGER NOT NULL REFERENCES manga(id) ON DELETE CASCADE,
                source_name TEXT NOT NULL,
                source_manga_id TEXT NOT NULL,
                source_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_name, source_manga_id)
            )
            """
        )

        cursor.execute(
            """
            INSERT INTO manga_sources_v4 (id, manga_id, source_name, source_manga_id, source_url, created_at, updated_at)
            SELECT id, manga_id, source_name, source_manga_id, source_url, created_at, updated_at
            FROM manga_sources
            """
        )

        cursor.execute("DROP TABLE manga_sources")
        cursor.execute("ALTER TABLE manga_sources_v4 RENAME TO manga_sources")

        cursor.execute("PRAGMA foreign_key_check")
        fk_violations = cursor.fetchall()
        if fk_violations:
            raise sqlite3.IntegrityError(f"Foreign key check failed after recreation: {fk_violations}")

    # Recreate indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_manga_sources_manga_id ON manga_sources(manga_id)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_manga_sources_lookup ON manga_sources(source_name, source_manga_id)")

    # Recreate trigger preventing updating manga_id if chapters exist
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_manga_sources_manga_id_update
        BEFORE UPDATE OF manga_id ON manga_sources
        FOR EACH ROW
        WHEN NEW.manga_id != OLD.manga_id AND (SELECT COUNT(*) FROM chapters WHERE manga_source_id = OLD.id) > 0
        BEGIN
            SELECT RAISE(ABORT, 'Cannot update manga_id: source already has associated chapters');
        END;
        """
    )


def _migration_005_chapter_source_identity(conn: sqlite3.Connection) -> None:
    """
    Migration 5: Add source_chapter_id, scanlation_group, published_at and language to chapters.
    Migrates uniqueness constraint to UNIQUE(manga_source_id, source_chapter_id).
    Safely upgrades existing databases preserving all existing chapters and chapter_pages.
    """
    cursor = conn.cursor()

    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='chapters'")
    row = cursor.fetchone()
    if not row:
        return
    table_sql = row[0]

    # Check if migration was already applied (source_chapter_id column exists)
    if "source_chapter_id" in table_sql:
        return

    # Check if foreign keys are currently active and cannot be disabled due to an outer transaction
    is_fk_active = bool(cursor.execute("PRAGMA foreign_keys").fetchone()[0])
    if is_fk_active:
        raise sqlite3.OperationalError(
            "Cannot execute migration 5 inside an active transaction: altering table "
            "'chapters' requires disabling foreign keys (PRAGMA foreign_keys = OFF), "
            "which SQLite prohibits within an active transaction. "
            "Commit or rollback the outer transaction before executing migrations."
        )

    # 1. Create new table chapters_v5 with extended columns and stable source identity
    cursor.execute(
        """
        CREATE TABLE chapters_v5 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manga_id INTEGER NOT NULL REFERENCES manga(id) ON DELETE CASCADE,
            manga_source_id INTEGER NOT NULL REFERENCES manga_sources(id) ON DELETE CASCADE,
            source_chapter_id TEXT,
            chapter_number REAL NOT NULL,
            volume_number INTEGER,
            title TEXT,
            language TEXT NOT NULL DEFAULT 'ru',
            scanlation_group TEXT,
            published_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(manga_source_id, source_chapter_id)
        )
        """
    )

    # 2. Inspect existing columns to dynamically copy data without failing on test tables
    cursor.execute("PRAGMA table_info(chapters)")
    existing_cols = {col[1] for col in cursor.fetchall()}

    select_cols = ["id", "manga_id", "manga_source_id", "chapter_number"]
    dest_cols = ["id", "manga_id", "manga_source_id", "chapter_number"]

    for opt in ("source_chapter_id", "volume_number", "title", "language", "scanlation_group", "published_at", "created_at", "updated_at"):
        if opt in existing_cols:
            select_cols.append(opt)
            dest_cols.append(opt)

    sel_str = ", ".join(select_cols)
    dest_str = ", ".join(dest_cols)

    cursor.execute(f"INSERT INTO chapters_v5 ({dest_str}) SELECT {sel_str} FROM chapters")

    # 3. Drop triggers referencing chapters before swap
    cursor.execute("DROP TRIGGER IF EXISTS trg_chapters_manga_id_insert")
    cursor.execute("DROP TRIGGER IF EXISTS trg_chapters_manga_id_update")
    cursor.execute("DROP TRIGGER IF EXISTS trg_manga_sources_manga_id_update")

    # 4. Swap tables safely
    cursor.execute("DROP TABLE chapters")
    cursor.execute("ALTER TABLE chapters_v5 RENAME TO chapters")

    # 5. Verify foreign key integrity
    cursor.execute("PRAGMA foreign_key_check")
    fk_violations = cursor.fetchall()
    if fk_violations:
        raise sqlite3.IntegrityError(f"Foreign key check failed after chapters migration: {fk_violations}")

    # 6. Recreate indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chapters_manga_id ON chapters(manga_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chapters_manga_source ON chapters(manga_source_id, chapter_number)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_chapters_source_lookup ON chapters(manga_source_id, source_chapter_id)")

    # 7. Recreate triggers on chapters and manga_sources
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_chapters_manga_id_insert
        BEFORE INSERT ON chapters
        FOR EACH ROW
        WHEN (SELECT manga_id FROM manga_sources WHERE id = NEW.manga_source_id) != NEW.manga_id
        BEGIN
            SELECT RAISE(ABORT, 'Foreign key mismatch: chapter manga_id does not match manga_sources.manga_id');
        END;
        """
    )
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_chapters_manga_id_update
        BEFORE UPDATE OF manga_id, manga_source_id ON chapters
        FOR EACH ROW
        WHEN (SELECT manga_id FROM manga_sources WHERE id = NEW.manga_source_id) != NEW.manga_id
        BEGIN
            SELECT RAISE(ABORT, 'Foreign key mismatch: chapter manga_id does not match manga_sources.manga_id');
        END;
        """
    )
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_manga_sources_manga_id_update
        BEFORE UPDATE OF manga_id ON manga_sources
        FOR EACH ROW
        WHEN NEW.manga_id != OLD.manga_id AND (SELECT COUNT(*) FROM chapters WHERE manga_source_id = OLD.id) > 0
        BEGIN
            SELECT RAISE(ABORT, 'Cannot update manga_id: source already has associated chapters');
        END;
        """
    )


def _migration_006_user_reading_progress(conn: sqlite3.Connection) -> None:
    """
    Migration 006: Create user_reading_progress table.
    Stores verified Telegram user reading state with cascading deletions.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_reading_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            manga_id INTEGER NOT NULL REFERENCES manga(id) ON DELETE CASCADE,
            chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL DEFAULT 1,
            total_pages INTEGER DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, manga_id)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_reading_progress_user_manga ON user_reading_progress(user_id, manga_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_reading_progress_updated ON user_reading_progress(user_id, updated_at DESC)"
    )


def _migration_007_user_library(conn: sqlite3.Connection) -> None:
    """
    Migration 007: Create user_library table.
    Stores personal bookmarked/starred manga per verified Telegram user.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_library (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            manga_id INTEGER NOT NULL REFERENCES manga(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, manga_id)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_library_user_created ON user_library(user_id, created_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_library_user_manga ON user_library(user_id, manga_id)"
    )


def _migration_008_canonical_chapters(conn: sqlite3.Connection) -> None:
    """
    Migration 008: Create canonical_chapters table and link provider chapters.
    Preserves all existing chapter IDs, reading progress, and supports multi-scanlation
    variants per chapter.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS canonical_chapters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            manga_id INTEGER NOT NULL REFERENCES manga(id) ON DELETE CASCADE,
            chapter_number REAL NOT NULL,
            volume_number INTEGER,
            title TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(manga_id, chapter_number)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_canonical_chapters_manga_num ON canonical_chapters(manga_id, chapter_number)"
    )

    # Check if chapters has canonical_chapter_id column
    cursor.execute("PRAGMA table_info(chapters)")
    columns = [row[1] for row in cursor.fetchall()]
    if "canonical_chapter_id" not in columns:
        cursor.execute(
            "ALTER TABLE chapters ADD COLUMN canonical_chapter_id INTEGER REFERENCES canonical_chapters(id) ON DELETE SET NULL"
        )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_chapters_canonical_id ON chapters(canonical_chapter_id)"
    )

    # Backfill canonical chapters from existing chapters
    cursor.execute(
        """
        INSERT OR IGNORE INTO canonical_chapters (manga_id, chapter_number, volume_number, title)
        SELECT manga_id, chapter_number, volume_number, title
        FROM chapters
        ORDER BY id ASC
        """
    )

    # Link chapters to their canonical chapter
    cursor.execute(
        """
        UPDATE chapters
        SET canonical_chapter_id = (
            SELECT cc.id
            FROM canonical_chapters cc
            WHERE cc.manga_id = chapters.manga_id
              AND cc.chapter_number = chapters.chapter_number
        )
        WHERE canonical_chapter_id IS NULL
        """
    )


def _migration_009_catalog_indexes(conn: sqlite3.Connection) -> None:
    """
    Migration 009: Add composite and filtering indexes for high-performance
    catalog sorting, collections, and multi-criteria search.
    Eliminates temporary B-trees in SQLite query planning.
    """
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(manga)")
    cols = {row[1] for row in cursor.fetchall()}

    if "rating" in cols and "views_count" in cols:
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_manga_popularity ON manga(rating DESC, views_count DESC)"
        )
    if "status" in cols:
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_manga_status ON manga(status)"
        )
    if "type" in cols:
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_manga_type ON manga(type)"
        )
    if "release_year" in cols:
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_manga_release_year ON manga(release_year)"
        )
    if "created_at" in cols:
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_manga_created_at ON manga(created_at DESC)"
        )


# List of ordered migrations: (version, name, runner_function)
MIGRATIONS: List[Tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "001_initial_catalog_schema", _migration_001_initial_catalog_schema),
    (2, "002_sources_authors_genres_chapters", _migration_002_sources_authors_genres_chapters),
    (3, "003_fts5_search_index", _migration_003_fts5_search_index),
    (4, "004_manga_sources_global_unique", _migration_004_manga_sources_global_unique),
    (5, "005_chapter_source_identity", _migration_005_chapter_source_identity),
    (6, "006_user_reading_progress", _migration_006_user_reading_progress),
    (7, "007_user_library", _migration_007_user_library),
    (8, "008_canonical_chapters", _migration_008_canonical_chapters),
    (9, "009_catalog_indexes", _migration_009_catalog_indexes),
]


def run_migrations(conn: sqlite3.Connection) -> None:
    """
    Run pending migrations sequentially inside transactions.
    Idempotent and safe for existing databases.
    """
    was_fk_on = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    if was_fk_on:
        conn.execute("PRAGMA foreign_keys = OFF")

    try:
        cursor = conn.cursor()

        # Ensure schema_migrations table exists
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
        else:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

        # Fetch applied migrations
        cursor.execute("SELECT version FROM schema_migrations")
        applied_versions = {row[0] for row in cursor.fetchall()}

        for version, name, migration_fn in MIGRATIONS:
            if version not in applied_versions:
                logger.info(f"Applying migration {version}: {name}...")

                started_tx = False
                use_savepoint = False
                sp_name = f"migration_{version}"

                if not conn.in_transaction:
                    conn.execute("BEGIN IMMEDIATE")
                    started_tx = True
                else:
                    conn.execute(f"SAVEPOINT {sp_name}")
                    use_savepoint = True

                try:
                    # Execute migration inside transaction
                    migration_fn(conn)
                    cursor.execute(
                        "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                        (version, name),
                    )
                    if use_savepoint:
                        conn.execute(f"RELEASE SAVEPOINT {sp_name}")
                    if started_tx:
                        conn.commit()
                    logger.info(f"Migration {version}: {name} applied successfully.")
                except Exception as e:
                    if use_savepoint:
                        conn.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
                        conn.execute(f"RELEASE SAVEPOINT {sp_name}")
                    elif started_tx or conn.in_transaction:
                        conn.rollback()
                    logger.error(f"Migration {version}: {name} failed: {e}")
                    raise
    finally:
        if was_fk_on:
            conn.execute("PRAGMA foreign_keys = ON")


def search_manga(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20,
    offset: int = 0,
) -> List[sqlite3.Row]:
    """
    Search manga using FTS5 if available, with graceful fallback to LIKE.
    """
    clean_query = query.strip()
    if not clean_query:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM manga ORDER BY rating DESC LIMIT ? OFFSET ?", (limit, offset))
        return cursor.fetchall()

    cursor = conn.cursor()

    # Check if FTS5 table exists
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='manga_search_index'"
    )
    has_fts5 = cursor.fetchone() is not None

    if has_fts5:
        try:
            # Prepare query for FTS5 (prefix search on terms)
            fts_terms = [re.sub(r'["*]', '', term) for term in clean_query.split() if term]
            if fts_terms:
                fts_query = " ".join(f'"{term}"*' for term in fts_terms)
                sql = """
                    SELECT m.*
                    FROM manga m
                    JOIN manga_search_index fts ON m.id = fts.manga_id
                    WHERE manga_search_index MATCH ?
                    ORDER BY rank
                    LIMIT ? OFFSET ?
                """
                cursor.execute(sql, (fts_query, limit, offset))
                return cursor.fetchall()
        except sqlite3.OperationalError as e:
            logger.warning(f"FTS5 query failed, falling back to LIKE: {e}")

    # Fallback to LIKE
    like_pattern = f"%{clean_query}%"
    sql = """
        SELECT * FROM manga
        WHERE title LIKE ? OR original_title LIKE ? OR description LIKE ?
        ORDER BY rating DESC
        LIMIT ? OFFSET ?
    """
    cursor.execute(sql, (like_pattern, like_pattern, like_pattern, limit, offset))
    return cursor.fetchall()
