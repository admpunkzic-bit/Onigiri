"""
Unified Catalog Service for Onigiri.

Coordinates search, catalog retrieval, and metadata synchronization
between external providers (e.g. MangaDex) and the local SQLite database.
Ensures Russian-only content, canonical Onigiri representations, and avoids
duplicating manga records.
"""

import asyncio
import logging
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Set, Tuple

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

# In-memory search cache: query_key -> (timestamp, List[MangaListRead])
_SEARCH_CACHE: Dict[str, Tuple[float, List[MangaListRead]]] = {}
SEARCH_CACHE_TTL_SECONDS = 300.0  # 5 minutes TTL


def normalize_title(title: Optional[str]) -> str:
    """
    Normalize title for safe cross-source comparison:
    lowercase, strip, collapse unicode punctuation and whitespace.
    """
    if not title:
        return ""
    t = title.lower().strip()
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


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
        Does NOT duplicate existing records on repeated runs for the same source.
        Per Team Lead directive: separate external items are not merged solely by title string.
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
            # Create new canonical manga in Onigiri catalog with unique slug
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

    def get_all_genres(self) -> List[GenreRead]:
        """Load all distinct genres that are associated with at least one manga, sorted alphabetically."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT g.id, g.name, g.slug, COUNT(mg.manga_id) as manga_count
            FROM genres g
            JOIN manga_genres mg ON mg.genre_id = g.id
            GROUP BY g.id
            HAVING manga_count > 0
            ORDER BY g.name ASC
            """
        )
        return [
            GenreRead(id=r["id"], name=r["name"], slug=r["slug"])
            for r in cursor.fetchall()
        ]

    async def search(
        self,
        query: Optional[str] = None,
        genres: Optional[List[str]] = None,
        excluded_genres: Optional[List[str]] = None,
        manga_type: Optional[str] = None,
        status: Optional[str] = None,
        author: Optional[str] = None,
        release_year: Optional[int] = None,
        sort_by: str = "popularity",
        sort_order: str = "desc",
        page: int = 1,
        limit: int = 20,
    ) -> List[MangaListRead]:
        """
        Unified search and multi-criteria catalog filtering endpoint.
        - Prioritizes Manga-Chan as PRIMARY and MangaDex as RESERVE for external search.
        - Supports text queries (FTS5 + LIKE fallback), genre inclusion/exclusion, format types,
          publication status, author/artist, release year, custom sorting, and pagination.
        - Utilizes composite database indexes for sub-millisecond sorting and query plan efficiency.
        - Employs in-memory TTL caching (5 minutes).
        """
        clean_query = (query or "").strip()
        clean_genres = sorted([g.strip() for g in (genres or []) if g.strip()])
        clean_ex_genres = sorted([g.strip() for g in (excluded_genres or []) if g.strip()])
        cache_key = (
            f"{clean_query.lower()}_{clean_genres}_{clean_ex_genres}_"
            f"{manga_type}_{status}_{author}_{release_year}_{sort_by}_{sort_order}_{page}_{limit}"
        )

        now = time.time()
        if cache_key in _SEARCH_CACHE:
            cached_at, cached_items = _SEARCH_CACHE[cache_key]
            if (now - cached_at) < SEARCH_CACHE_TTL_SECONDS:
                return cached_items

        provider_manga_ids: List[int] = []

        # 1. If text query is present, query external providers concurrently
        if self.registry and clean_query:
            tasks = []
            task_providers = []

            if self.registry.has("mangachan"):
                chan_prov = self.registry.get("mangachan")
                tasks.append(
                    asyncio.wait_for(
                        chan_prov.search(query=clean_query, page=page, limit=limit, languages=["ru"]),
                        timeout=2.5,
                    )
                )
                task_providers.append("mangachan")

            if self.registry.has("mangadex"):
                dex_prov = self.registry.get("mangadex")
                tasks.append(
                    asyncio.wait_for(
                        dex_prov.search(query=clean_query, page=page, limit=limit, languages=["ru"]),
                        timeout=2.0,
                    )
                )
                task_providers.append("mangadex")

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)

                chan_items: List[ProviderMangaItem] = []
                dex_items: List[ProviderMangaItem] = []

                for prov_name, res in zip(task_providers, results):
                    if isinstance(res, Exception):
                        logger.warning("Provider '%s' search encountered error or timeout: %s", prov_name, res)
                        continue
                    if isinstance(res, ProviderSearchResult) and res.items:
                        if prov_name == "mangachan":
                            chan_items = res.items
                        elif prov_name == "mangadex":
                            dex_items = res.items

                # Primary (Manga-Chan) upserted first
                for item in chan_items:
                    m_id = self.upsert_provider_manga(item)
                    if m_id not in provider_manga_ids:
                        provider_manga_ids.append(m_id)

                # Reserve (MangaDex) items appended next
                for item in dex_items:
                    m_id = self.upsert_provider_manga(item)
                    if m_id not in provider_manga_ids:
                        provider_manga_ids.append(m_id)

        # 2. Build dynamic SQLite query with all active filters
        cursor = self.conn.cursor()
        where_clauses: List[str] = []
        params: List[Any] = []

        if clean_query:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='manga_search_index'")
            has_fts5 = cursor.fetchone() is not None
            if has_fts5:
                fts_terms = [re.sub(r'["*]', '', term) for term in clean_query.split() if term]
                if fts_terms:
                    fts_expr = " ".join(f'"{term}"*' for term in fts_terms)
                    where_clauses.append("m.id IN (SELECT manga_id FROM manga_search_index WHERE manga_search_index MATCH ?)")
                    params.append(fts_expr)
                else:
                    where_clauses.append("(m.title LIKE ? OR m.original_title LIKE ?)")
                    params.extend([f"%{clean_query}%", f"%{clean_query}%"])
            else:
                where_clauses.append("(m.title LIKE ? OR m.original_title LIKE ? OR m.description LIKE ?)")
                params.extend([f"%{clean_query}%", f"%{clean_query}%", f"%{clean_query}%"])

        if clean_genres:
            for g_term in clean_genres:
                where_clauses.append(
                    """
                    m.id IN (
                        SELECT mg.manga_id FROM manga_genres mg
                        JOIN genres g ON g.id = mg.genre_id
                        WHERE g.slug = ? OR LOWER(g.name) = LOWER(?)
                    )
                    """
                )
                params.extend([g_term, g_term])

        if clean_ex_genres:
            ph = ",".join("?" for _ in clean_ex_genres)
            where_clauses.append(
                f"""
                m.id NOT IN (
                    SELECT mg_ex.manga_id FROM manga_genres mg_ex
                    JOIN genres g_ex ON g_ex.id = mg_ex.genre_id
                    WHERE g_ex.slug IN ({ph}) OR LOWER(g_ex.name) IN ({ph})
                )
                """
            )
            params.extend(clean_ex_genres)
            params.extend([g.lower() for g in clean_ex_genres])

        if manga_type:
            where_clauses.append("LOWER(m.type) = LOWER(?)")
            params.append(manga_type.strip())

        if status:
            where_clauses.append("LOWER(m.status) = LOWER(?)")
            params.append(status.strip())

        if author:
            where_clauses.append(
                """
                m.id IN (
                    SELECT ma.manga_id FROM manga_authors ma
                    JOIN authors a ON a.id = ma.author_id
                    WHERE LOWER(a.name) LIKE ?
                )
                """
            )
            params.append(f"%{author.strip().lower()}%")

        if release_year:
            where_clauses.append("m.release_year = ?")
            params.append(release_year)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        order_dir = "DESC" if sort_order.lower() == "desc" else "ASC"
        sort_key = sort_by.lower()
        if sort_key == "rating":
            order_sql = f"ORDER BY m.rating {order_dir}, m.views_count {order_dir}"
        elif sort_key in ("views", "popularity"):
            order_sql = f"ORDER BY m.rating {order_dir}, m.views_count {order_dir}, m.id {order_dir}"
        elif sort_key == "updated_at":
            order_sql = f"ORDER BY m.updated_at {order_dir}"
        elif sort_key == "created_at":
            order_sql = f"ORDER BY m.created_at {order_dir}"
        else:
            order_sql = f"ORDER BY m.rating {order_dir}, m.views_count {order_dir}, m.id {order_dir}"

        offset = (page - 1) * limit
        sql = f"SELECT m.id FROM manga m {where_sql} {order_sql} LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(sql, params)
        local_manga_ids = [row["id"] for row in cursor.fetchall()]

        combined_ids: List[int] = []
        for mid in provider_manga_ids + local_manga_ids:
            if mid not in combined_ids:
                combined_ids.append(mid)

        final_ids = combined_ids[:limit]
        loaded_items = self._load_manga_list_items(final_ids)

        _SEARCH_CACHE[cache_key] = (now, loaded_items)
        return loaded_items

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
        """
        Load chapters for manga with ordering by chapter number.
        Deduplicates identical chapter releases in favor of Manga-Chan (Primary),
        while strictly preserving distinct alternative translations (different scanlation groups).
        """
        cursor = self.conn.cursor()
        order_dir = "ASC" if order.lower() == "asc" else "DESC"
        cursor.execute(
            f"""
            SELECT c.id, c.manga_id, c.manga_source_id, c.source_chapter_id, c.canonical_chapter_id, c.chapter_number,
                   c.volume_number, c.title, c.language, c.scanlation_group, c.published_at,
                   c.created_at, c.updated_at, ms.source_name
            FROM chapters c
            LEFT JOIN manga_sources ms ON ms.id = c.manga_source_id
            WHERE c.manga_id = ? AND c.language = 'ru'
            ORDER BY c.chapter_number {order_dir}, c.id {order_dir}
            """,
            (manga_id,),
        )
        raw_rows = cursor.fetchall()

        # Multi-source deduplication:
        # Prefer Manga-Chan (Primary) for duplicate releases with same number and group,
        # while keeping distinct alternative translations.
        seen_keys: Set[Tuple[float, Optional[str]]] = set()
        chapters: List[ChapterRead] = []

        def sort_priority(r: sqlite3.Row) -> int:
            return 0 if (r["source_name"] == "mangachan") else 1

        sorted_rows = sorted(raw_rows, key=sort_priority)

        for c in sorted_rows:
            ch_num = c["chapter_number"] if c["chapter_number"] is not None else 0.0
            group_key = (c["scanlation_group"] or "").strip().lower()
            dedup_key = (ch_num, group_key if group_key else None)

            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            chapters.append(
                ChapterRead(
                    id=c["id"],
                    manga_id=c["manga_id"],
                    manga_source_id=c["manga_source_id"],
                    source_chapter_id=c["source_chapter_id"],
                    canonical_chapter_id=c["canonical_chapter_id"],
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

        if order.lower() == "desc":
            chapters.sort(key=lambda x: (x.chapter_number if x.chapter_number is not None else 0.0, x.id), reverse=True)
        else:
            chapters.sort(key=lambda x: (x.chapter_number if x.chapter_number is not None else 0.0, x.id))

        return chapters

    async def sync_manga_chapters(self, manga_id: int) -> List[ChapterRead]:
        """
        Fetch all Russian chapters with Manga-Chan as PRIMARY and MangaDex as RESERVE.
        1. Discovers and links Manga-Chan source if not yet connected to this manga.
        2. Syncs Manga-Chan chapters first.
        3. Evaluates available Russian chapters count.
        4. If Manga-Chan has chapters (> 0), uses Manga-Chan as primary and supplements from MangaDex.
        5. If Manga-Chan has 0 chapters or fails, falls back to MangaDex.
        6. Reconciles into canonical_chapters without duplicates while preserving alternative translations.
        """
        if not self.registry:
            return self._load_manga_chapters(manga_id)

        cursor = self.conn.cursor()

        # Step 1: Ensure Manga-Chan is linked if available in registry
        cursor.execute(
            "SELECT id FROM manga_sources WHERE manga_id = ? AND source_name = 'mangachan'",
            (manga_id,),
        )
        chan_source = cursor.fetchone()

        if not chan_source and self.registry.has("mangachan"):
            cursor.execute("SELECT title, original_title FROM manga WHERE id = ?", (manga_id,))
            m_info = cursor.fetchone()
            if m_info:
                query_title = m_info["title"]
                try:
                    chan_prov = self.registry.get("mangachan")
                    search_res = await chan_prov.search(query=query_title, page=1, limit=5)
                    matching_item = None
                    if search_res.items:
                        norm_db = normalize_title(query_title)
                        for it in search_res.items:
                            all_it = [it.title] + (it.alt_titles or [])
                            if any(normalize_title(t) == norm_db for t in all_it):
                                matching_item = it
                                break
                        if not matching_item and search_res.items:
                            first_slug = slugify(search_res.items[0].title)
                            if first_slug == slugify(query_title):
                                matching_item = search_res.items[0]

                    if matching_item:
                        logger.info(
                            "Linking Primary Manga-Chan '%s' to manga %d ('%s')",
                            matching_item.provider_manga_id,
                            manga_id,
                            query_title,
                        )
                        cursor.execute(
                            """
                            INSERT INTO manga_sources (manga_id, source_name, source_manga_id, source_url)
                            VALUES (?, 'mangachan', ?, ?)
                            ON CONFLICT(source_name, source_manga_id) DO UPDATE SET
                                manga_id = excluded.manga_id,
                                source_url = excluded.source_url,
                                updated_at = CURRENT_TIMESTAMP
                            """,
                            (
                                manga_id,
                                matching_item.provider_manga_id,
                                matching_item.source_url,
                            ),
                        )
                        self.conn.commit()
                except Exception as exc:
                    logger.warning("Error discovering Manga-Chan for manga %d: %s", manga_id, exc)

        # Step 2: Fetch and order sources: Manga-Chan (Primary) FIRST, MangaDex SECOND
        cursor.execute(
            "SELECT id, source_name, source_manga_id FROM manga_sources WHERE manga_id = ?",
            (manga_id,),
        )
        sources = cursor.fetchall()
        # Sort so mangachan is first
        sources.sort(key=lambda s: 0 if s["source_name"] == "mangachan" else 1)

        mangachan_chapters_count = 0

        for src in sources:
            src_id = src["id"]
            src_name = src["source_name"]
            src_manga_id = src["source_manga_id"]

            if not self.registry.has(src_name):
                continue

            provider = self.registry.get(src_name)
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
                    logger.error("Error fetching chapters for source %s (%s, page %d): %s", src_manga_id, src_name, page, exc)
                    break

                if not isinstance(res, ProviderChaptersResult) or not res.chapters:
                    break

                for ch in res.chapters:
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
                    if src_name == "mangachan":
                        mangachan_chapters_count += 1

                self.conn.commit()

                if not res.has_next:
                    break
                page += 1
                await asyncio.sleep(0.05)

        # Step 3: Reconcile into canonical_chapters
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
        self.conn.commit()

        return self._load_manga_chapters(manga_id)

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

            if not row and self.registry.has("mangachan"):
                try:
                    chan_provider = self.registry.get("mangachan")
                    chan_item = await chan_provider.get_manga_details(clean_identifier)
                    if chan_item:
                        m_id = self.upsert_provider_manga(chan_item)
                        row = self._find_manga_row(str(m_id))
                except Exception as exc:
                    logger.debug("Identifier '%s' could not be resolved via Manga-Chan: %s", clean_identifier, exc)

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

    async def add_to_library(self, user_id: str, id_or_slug: str) -> Optional[MangaListRead]:
        """
        Add manga to user's personal library.
        If manga is not present locally, provisions it from registered provider.
        Returns the compact MangaListRead representation.
        """
        row = self._find_manga_row(id_or_slug)
        if not row and self.registry:
            # Attempt to auto-provision by external UUID/slug
            detail = await self.get_manga_by_id_or_slug(id_or_slug, auto_sync_chapters=False)
            if detail:
                row = self._find_manga_row(str(detail.id))

        if not row:
            return None

        manga_id = row["id"]
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT OR IGNORE INTO user_library (user_id, manga_id)
            VALUES (?, ?)
            """,
            (user_id, manga_id),
        )
        self.conn.commit()

        items = self._load_manga_list_items([manga_id])
        return items[0] if items else None

    def remove_from_library(self, user_id: str, id_or_slug: str) -> bool:
        """
        Remove manga from user's personal library.
        Returns True if item was removed, False if not found.
        """
        row = self._find_manga_row(id_or_slug)
        if not row:
            return False

        manga_id = row["id"]
        cursor = self.conn.cursor()
        cursor.execute(
            "DELETE FROM user_library WHERE user_id = ? AND manga_id = ?",
            (user_id, manga_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get_user_library(self, user_id: str) -> List[MangaListRead]:
        """
        Retrieve all manga bookmarked in user's library, sorted by added date descending.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT manga_id FROM user_library WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        manga_ids = [row["manga_id"] for row in cursor.fetchall()]
        return self._load_manga_list_items(manga_ids)

    def get_user_library_manga_ids(self, user_id: str) -> List[int]:
        """
        Retrieve lightweight list of manga IDs bookmarked in user's library.
        Used for fast star state checking in catalog grids and search.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT manga_id FROM user_library WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        return [row["manga_id"] for row in cursor.fetchall()]
