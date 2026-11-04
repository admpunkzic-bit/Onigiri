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
            UNIQUE(manga_id, source_name, source_manga_id)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_manga_sources_manga_id ON manga_sources(manga_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_manga_sources_lookup ON manga_sources(source_name, source_manga_id)")

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


# List of ordered migrations: (version, name, runner_function)
MIGRATIONS: List[Tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "001_initial_catalog_schema", _migration_001_initial_catalog_schema),
    (2, "002_sources_authors_genres_chapters", _migration_002_sources_authors_genres_chapters),
    (3, "003_fts5_search_index", _migration_003_fts5_search_index),
]


def run_migrations(conn: sqlite3.Connection) -> None:
    """
    Run pending migrations sequentially inside transactions.
    Idempotent and safe for existing databases.
    """
    cursor = conn.cursor()

    # Ensure schema_migrations table exists
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

    # Fetch applied migrations
    cursor.execute("SELECT version FROM schema_migrations")
    applied_versions = {row[0] for row in cursor.fetchall()}

    for version, name, migration_fn in MIGRATIONS:
        if version not in applied_versions:
            logger.info(f"Applying migration {version}: {name}...")
            try:
                # Execute migration inside transaction
                migration_fn(conn)
                cursor.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                    (version, name),
                )
                conn.commit()
                logger.info(f"Migration {version}: {name} applied successfully.")
            except Exception as e:
                conn.rollback()
                logger.error(f"Migration {version}: {name} failed: {e}")
                raise


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
