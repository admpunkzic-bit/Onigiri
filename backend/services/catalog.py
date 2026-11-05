"""
Unified Catalog Service for Onigiri.

Coordinates search, catalog retrieval, and metadata synchronization
between external providers (e.g. MangaDex) and the local SQLite database.
Ensures Russian-only content, canonical Onigiri representations, and avoids
duplicating manga records.
"""

import asyncio
import logging
import sqlite3
from typing import Dict, List, Optional, Set

from database.migrations import is_fts5_available, search_manga, slugify
from providers.base import (
    BaseMangaProvider,
    ProviderChaptersResult,
    ProviderError,
    ProviderMangaItem,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderSearchResult,
)
from providers.registry import ProviderRegistry
from schemas.manga import (
    AuthorRead,
    ChapterRead,
    GenreRead,
    MangaDetailRead,
    MangaListRead,
)

logger = logging.getLogger(__name__)

# Allowed canonical manga status values in Onigiri
VALID_STATUSES: Set[str] = {"ongoing", "completed", "hiatus", "cancelled"}


class CatalogService:
    """
    Unified catalog manager for Onigiri manga titles.
    Interacts with external providers and internal SQLite storage.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        registry: Optional[ProviderRegistry] = None,
    ) -> None:
        self.conn = conn
        self.registry = registry

    def _get_or_create_genre(self, genre_name: str) -> int:
        """Retrieve existing genre ID or insert new genre with a unique slug."""
        clean_name = genre_name.strip()
        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM genres WHERE name = ?", (clean_name,))
        row = cursor.fetchone()
        if row:
            return row["id"]

        base_slug = slugify(clean_name) or "genre"
        unique_slug = base_slug
        counter = 1
        while True:
            cursor.execute("SELECT id FROM genres WHERE slug = ?", (unique_slug,))
            if not cursor.fetchone():
                break
            counter += 1
            unique_slug = f"{base_slug}-{counter}"

        cursor.execute(
            "INSERT INTO genres (name, slug) VALUES (?, ?)",
            (clean_name, unique_slug),
        )
        return cursor.lastrowid

    def _get_or_create_author(self, author_name: str) -> int:
        """Retrieve existing author ID or insert a new author."""
        clean_name = author_name.strip()
        cursor = self.conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO authors (name) VALUES (?)", (clean_name,))
        cursor.execute("SELECT id FROM authors WHERE name = ?", (clean_name,))
        row = cursor.fetchone()
        return row["id"]

    def _generate_unique_manga_slug(self, title: str) -> str:
        """Generate a unique slug for a new manga record."""
        base_slug = slugify(title) or "manga"
        unique_slug = base_slug
        counter = 1
        cursor = self.conn.cursor()
        while True:
            cursor.execute("SELECT id FROM manga WHERE slug = ?", (unique_slug,))
            if not cursor.fetchone():
                break
            counter += 1
            unique_slug = f"{base_slug}-{counter}"
        return unique_slug

    def upsert_provider_manga(self, item: ProviderMangaItem) -> int:
        """
        Map external provider manga item to Onigiri canonical manga.
        Links via manga_sources (source_name, source_manga_id).
        Does NOT duplicate existing records on repeated runs.
        """
        cursor = self.conn.cursor()

        # 1. Exact match on source_name + source_manga_id
        cursor.execute(
            """
            SELECT manga_id FROM manga_sources
            WHERE source_name = ? AND source_manga_id = ?
            """,
            (item.provider_id, item.provider_manga_id),
        )
        existing_source = cursor.fetchone()

        if existing_source:
            manga_id = existing_source["manga_id"]
            # Fill in any missing metadata if available in external item
            alt_title = item.alt_titles[0] if item.alt_titles else None
            cursor.execute(
                """
                UPDATE manga
                SET description = COALESCE(description, ?),
                    cover_url = COALESCE(cover_url, ?),
                    release_year = COALESCE(release_year, ?),
                    original_title = COALESCE(original_title, ?),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (item.description, item.cover_url, item.release_year, alt_title, manga_id),
            )
        else:
            # Create new canonical manga in Onigiri catalog
            slug = self._generate_unique_manga_slug(item.title)
            status_lower = item.status.lower() if item.status else "ongoing"
            status = status_lower if status_lower in VALID_STATUSES else "ongoing"
            alt_title = item.alt_titles[0] if item.alt_titles else None

            cursor.execute(
                """
                INSERT INTO manga (
                    title, slug, original_title, description, cover_url,
                    status, type, release_year, rating, views_count
                ) VALUES (?, ?, ?, ?, ?, ?, 'manga', ?, 0.0, 0)
                """,
                (
                    item.title,
                    slug,
                    alt_title,
                    item.description,
                    item.cover_url,
                    status,
                    item.release_year,
                ),
            )
            manga_id = cursor.lastrowid

            # Create external source reference
            cursor.execute(
                """
                INSERT INTO manga_sources (manga_id, source_name, source_manga_id, source_url)
                VALUES (?, ?, ?, ?)
                """,
                (manga_id, item.provider_id, item.provider_manga_id, item.source_url),
            )

        # 2. Synchronize authors and artists
        for author_name in item.authors:
            clean_name = author_name.strip()
            if clean_name:
                author_id = self._get_or_create_author(clean_name)
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO manga_authors (manga_id, author_id, role)
                    VALUES (?, ?, 'author')
                    """,
                    (manga_id, author_id),
                )

        for artist_name in item.artists:
            clean_name = artist_name.strip()
            if clean_name:
                artist_id = self._get_or_create_author(clean_name)
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO manga_authors (manga_id, author_id, role)
                    VALUES (?, ?, 'artist')
                    """,
                    (manga_id, artist_id),
                )

        # 3. Synchronize genres
        for genre_name in item.genres:
            clean_genre = genre_name.strip()
            if clean_genre:
                genre_id = self._get_or_create_genre(clean_genre)
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO manga_genres (manga_id, genre_id)
                    VALUES (?, ?)
                    """,
                    (manga_id, genre_id),
                )

        self.conn.commit()
        return manga_id

    def _load_manga_list_items(self, manga_ids: List[int]) -> List[MangaListRead]:
        """Load fully populated MangaListRead DTOs for a given list of manga IDs."""
        if not manga_ids:
            return []

        cursor = self.conn.cursor()
        placeholders = ",".join("?" for _ in manga_ids)

        cursor.execute(
            f"SELECT * FROM manga WHERE id IN ({placeholders})",
            manga_ids,
        )
        rows = {row["id"]: row for row in cursor.fetchall()}

        # Load authors for all requested IDs
        cursor.execute(
            f"""
            SELECT ma.manga_id, a.id, a.name, ma.role
            FROM manga_authors ma
            JOIN authors a ON a.id = ma.author_id
            WHERE ma.manga_id IN ({placeholders})
            ORDER BY a.name ASC
            """,
            manga_ids,
        )
        authors_by_manga: Dict[int, List[AuthorRead]] = {m_id: [] for m_id in manga_ids}
        for row in cursor.fetchall():
            authors_by_manga[row["manga_id"]].append(
                AuthorRead(id=row["id"], name=row["name"], role=row["role"])
            )

        # Load genres for all requested IDs
        cursor.execute(
            f"""
            SELECT mg.manga_id, g.id, g.name, g.slug
            FROM manga_genres mg
            JOIN genres g ON g.id = mg.genre_id
            WHERE mg.manga_id IN ({placeholders})
            ORDER BY g.name ASC
            """,
            manga_ids,
        )
        genres_by_manga: Dict[int, List[GenreRead]] = {m_id: [] for m_id in manga_ids}
        for row in cursor.fetchall():
            genres_by_manga[row["manga_id"]].append(
                GenreRead(id=row["id"], name=row["name"], slug=row["slug"])
            )

        results: List[MangaListRead] = []
        for m_id in manga_ids:
            if m_id not in rows:
                continue
            r = rows[m_id]
            results.append(
                MangaListRead(
                    id=r["id"],
                    title=r["title"],
                    slug=r["slug"],
                    original_title=r["original_title"],
                    cover_url=r["cover_url"],
                    status=r["status"],
                    type=r["type"],
                    release_year=r["release_year"],
                    rating=r["rating"],
                    views_count=r["views_count"],
                    genres=genres_by_manga.get(m_id, []),
                    authors=authors_by_manga.get(m_id, []),
                )
            )

        return results

    async def search(
        self,
        query: str,
        page: int = 1,
        limit: int = 20,
    ) -> List[MangaListRead]:
        """
        Unified search endpoint.
        1. Queries external provider (MangaDex) strictly for Russian translations.
        2. Upserts discovered titles into local catalog (manga, manga_sources, genres, authors).
        3. Retrieves and returns Onigiri canonical MangaListRead representations.
        4. Gracefully degrades to local catalog if provider query fails.
        """
        clean_query = query.strip()
        provider_manga_ids: List[int] = []

        # 1. Fetch from MangaDex via ProviderRegistry if available
        if self.registry and clean_query:
            try:
                provider = self.registry.get("mangadex")
                provider_res: ProviderSearchResult = await provider.search(
                    query=clean_query,
                    page=page,
                    limit=limit,
                    languages=["ru"],
                )
                for item in provider_res.items:
                    m_id = self.upsert_provider_manga(item)
                    if m_id not in provider_manga_ids:
                        provider_manga_ids.append(m_id)
            except (ProviderNetworkError, ProviderRateLimitError) as exc:
                logger.warning("External provider search degraded gracefully: %s", exc)
            except ProviderError as exc:
                logger.error("External provider error during catalog search: %s", exc)
            except Exception as exc:
                logger.exception("Unexpected error querying provider: %s", exc)

        # 2. Query local SQLite database (FTS5 search with LIKE fallback)
        offset = (page - 1) * limit
        local_rows = search_manga(self.conn, clean_query, limit=limit, offset=offset)
        local_manga_ids = [row["id"] for row in local_rows]

        # 3. Combine provider-found IDs and local IDs while preserving order and uniqueness
        combined_ids: List[int] = []
        for mid in provider_manga_ids + local_manga_ids:
            if mid not in combined_ids:
                combined_ids.append(mid)

        # Truncate to limit
        final_ids = combined_ids[:limit]

        return self._load_manga_list_items(final_ids)

    def _find_manga_row(self, identifier: str) -> Optional[sqlite3.Row]:
        """
        Locate manga row by Onigiri numeric ID, slug, or external source_manga_id (UUID).
        """
        cursor = self.conn.cursor()
        clean = identifier.strip()

        # 1. Numeric ID
        if clean.isdigit():
            cursor.execute("SELECT * FROM manga WHERE id = ?", (int(clean),))
            row = cursor.fetchone()
            if row:
                return row

        # 2. Slug
        cursor.execute("SELECT * FROM manga WHERE slug = ?", (clean,))
        row = cursor.fetchone()
        if row:
            return row

        # 3. External source_manga_id (e.g. MangaDex UUID)
        cursor.execute(
            """
            SELECT m.*
            FROM manga m
            JOIN manga_sources ms ON ms.manga_id = m.id
            WHERE ms.source_manga_id = ?
            LIMIT 1
            """,
            (clean,),
        )
        return cursor.fetchone()

    def _load_manga_chapters(self, manga_id: int, order: str = "asc") -> List[ChapterRead]:
        """Load chapters for manga with ordering by chapter number."""
        cursor = self.conn.cursor()
        order_dir = "ASC" if order.lower() == "asc" else "DESC"
        cursor.execute(
            f"""
            SELECT id, manga_id, manga_source_id, source_chapter_id, chapter_number,
                   volume_number, title, language, scanlation_group, published_at,
                   created_at, updated_at
            FROM chapters
            WHERE manga_id = ?
            ORDER BY chapter_number {order_dir}, id {order_dir}
            """,
            (manga_id,),
        )
        chapters: List[ChapterRead] = []
        for c in cursor.fetchall():
            chapters.append(
                ChapterRead(
                    id=c["id"],
                    manga_id=c["manga_id"],
                    manga_source_id=c["manga_source_id"],
                    source_chapter_id=c["source_chapter_id"],
                    chapter_number=c["chapter_number"],
                    volume_number=c["volume_number"],
                    title=c["title"],
                    language=c["language"] or "ru",
                    scanlation_group=c["scanlation_group"],
                    published_at=c["published_at"],
                    created_at=c["created_at"],
                    updated_at=c["updated_at"],
                )
            )
        return chapters

    async def sync_manga_chapters(self, manga_id: int) -> List[ChapterRead]:
        """
        Fetch all Russian chapters from external providers (e.g. MangaDex)
        and idempotently persist them into the SQLite chapters table.
        Follows pagination across all pages to sync the full chapter list.
        Enforces Russian-only language restriction and safe deduplication.
        """
        if not self.registry:
            return self._load_manga_chapters(manga_id)

        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT id, source_name, source_manga_id FROM manga_sources WHERE manga_id = ?",
            (manga_id,),
        )
        sources = cursor.fetchall()
        if not sources:
            return self._load_manga_chapters(manga_id)

        for src in sources:
            src_id = src["id"]
            src_name = src["source_name"]
            src_manga_id = src["source_manga_id"]

            try:
                provider = self.registry.get(src_name)
            except Exception as exc:
                logger.warning("Provider '%s' not available for sync: %s", src_name, exc)
                continue

            page = 1
            limit = 100
            max_pages = 50
            while page <= max_pages:
                try:
                    res = await provider.get_chapters(
                        provider_manga_id=src_manga_id,
                        language="ru",
                        page=page,
                        limit=limit,
                    )
                except Exception as exc:
                    logger.error("Error fetching chapters for source %s (page %d): %s", src_manga_id, page, exc)
                    break

                if not isinstance(res, ProviderChaptersResult) or not res.chapters:
                    break

                for ch in res.chapters:
                    # Strict Russian language validation
                    if getattr(ch, "language", None) != "ru":
                        continue

                    ch_num = ch.chapter_number_numeric if ch.chapter_number_numeric is not None else 0.0

                    cursor.execute(
                        """
                        INSERT INTO chapters (
                            manga_id,
                            manga_source_id,
                            source_chapter_id,
                            chapter_number,
                            volume_number,
                            title,
                            language,
                            scanlation_group,
                            published_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(manga_source_id, source_chapter_id) DO UPDATE SET
                            chapter_number = excluded.chapter_number,
                            volume_number = excluded.volume_number,
                            title = excluded.title,
                            language = excluded.language,
                            scanlation_group = excluded.scanlation_group,
                            published_at = excluded.published_at,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (
                            manga_id,
                            src_id,
                            ch.provider_chapter_id,
                            ch_num,
                            ch.volume_number,
                            ch.title,
                            "ru",
                            ch.scanlation_group,
                            ch.published_at.isoformat() if ch.published_at else None,
                        ),
                    )

                self.conn.commit()

                if not res.has_next:
                    break
                page += 1
                await asyncio.sleep(0.05)

        return self._load_manga_chapters(manga_id)

    async def get_manga_by_id_or_slug(
        self,
        id_or_slug: str,
        auto_sync_chapters: bool = True,
    ) -> Optional[MangaDetailRead]:
        """
        Retrieve manga details by internal Onigiri ID, unique slug, or external provider UUID.
        Automatically provisions manga from external provider if accessed by valid provider UUID.
        Automatically synchronizes chapters if none are currently stored.
        Increments view count and populates authors, genres, and chapters.
        External provider details and source names are omitted from public response.
        """
        cursor = self.conn.cursor()
        clean_identifier = id_or_slug.strip()

        row = self._find_manga_row(clean_identifier)

        # If not found locally, attempt to resolve via registered provider if clean_identifier resembles external ID
        if not row and self.registry:
            try:
                provider = self.registry.get("mangadex")
                external_item = await provider.get_manga_details(clean_identifier)
                if external_item:
                    # Enforce Russian availability check if declared
                    if not external_item.available_languages or "ru" in external_item.available_languages:
                        m_id = self.upsert_provider_manga(external_item)
                        row = self._find_manga_row(str(m_id))
            except Exception as exc:
                logger.debug("Identifier '%s' could not be resolved directly via provider: %s", clean_identifier, exc)

        if not row:
            return None

        manga_id = row["id"]

        # Increment view count
        cursor.execute(
            "UPDATE manga SET views_count = views_count + 1 WHERE id = ?",
            (manga_id,),
        )
        self.conn.commit()

        # Load authors
        cursor.execute(
            """
            SELECT a.id, a.name, ma.role
            FROM manga_authors ma
            JOIN authors a ON a.id = ma.author_id
            WHERE ma.manga_id = ?
            ORDER BY a.name ASC
            """,
            (manga_id,),
        )
        authors = [
            AuthorRead(id=a["id"], name=a["name"], role=a["role"])
            for a in cursor.fetchall()
        ]

        # Load genres
        cursor.execute(
            """
            SELECT g.id, g.name, g.slug
            FROM manga_genres mg
            JOIN genres g ON g.id = mg.genre_id
            WHERE mg.manga_id = ?
            ORDER BY g.name ASC
            """,
            (manga_id,),
        )
        genres = [
            GenreRead(id=g["id"], name=g["name"], slug=g["slug"])
            for g in cursor.fetchall()
        ]

        # Check if chapters exist, otherwise perform automatic sync on first visit
        cursor.execute("SELECT COUNT(*) FROM chapters WHERE manga_id = ?", (manga_id,))
        chapters_count = cursor.fetchone()[0]

        if chapters_count == 0 and auto_sync_chapters and self.registry:
            chapters = await self.sync_manga_chapters(manga_id)
        else:
            chapters = self._load_manga_chapters(manga_id)

        return MangaDetailRead(
            id=row["id"],
            title=row["title"],
            slug=row["slug"],
            original_title=row["original_title"],
            description=row["description"],
            cover_url=row["cover_url"],
            banner_url=row["banner_url"],
            status=row["status"],
            type=row["type"],
            release_year=row["release_year"],
            rating=row["rating"],
            views_count=row["views_count"] + 1,  # reflects incremented views
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            genres=genres,
            authors=authors,
            sources=[],  # External provider sources are not exposed to the user
            chapters=chapters,
        )

    async def get_chapters_for_manga(
        self,
        id_or_slug: str,
        order: str = "asc",
    ) -> Optional[List[ChapterRead]]:
        """Retrieve chapter list for a manga by ID, slug, or external UUID with specified ordering."""
        row = self._find_manga_row(id_or_slug)
        if not row:
            return None
        manga_id = row["id"]

        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM chapters WHERE manga_id = ?", (manga_id,))
        if cursor.fetchone()[0] == 0 and self.registry:
            await self.sync_manga_chapters(manga_id)

        return self._load_manga_chapters(manga_id, order=order)
