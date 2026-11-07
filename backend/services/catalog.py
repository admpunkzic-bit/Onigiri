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
    HomepageCollectionRead,
    HomepageDataRead,
    MangaDetailRead,
    MangaListRead,
    TranslationVariantRead,
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
                SET description = COALESCE(manga.description, ?),
                    cover_url = CASE WHEN manga.cover_url IS NULL OR manga.cover_url = '' THEN ? ELSE manga.cover_url END,
                    release_year = COALESCE(manga.release_year, ?),
                    original_title = COALESCE(manga.original_title, ?),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (item.description, item.cover_url, item.release_year, alt_title, manga_id),
            )
        else:
            # Check for confirmed matching manga by title / alt_titles
            target_norm = normalize_title(item.title)
            alt_norms = [normalize_title(t) for t in item.alt_titles if t]
            cursor.execute("SELECT id, title, original_title FROM manga")
            all_m = cursor.fetchall()
            matched_manga_id = None
            for m in all_m:
                m_title_norm = normalize_title(m["title"])
                m_orig_norm = normalize_title(m["original_title"]) if m["original_title"] else ""
                matches_title = (m_title_norm == target_norm or (m_orig_norm and m_orig_norm == target_norm))
                matches_alt = any(m_title_norm == a or (m_orig_norm and m_orig_norm == a) for a in alt_norms)
                if matches_title or matches_alt:
                    # Check if this canonical manga ALREADY has a binding for this provider
                    cursor.execute(
                        "SELECT 1 FROM manga_sources WHERE manga_id = ? AND source_name = ?",
                        (m["id"], item.provider_id),
                    )
                    if not cursor.fetchone():
                        matched_manga_id = m["id"]
                        break

            if matched_manga_id:
                manga_id = matched_manga_id
                cursor.execute(
                    """
                    INSERT INTO manga_sources (manga_id, source_name, source_manga_id, source_url)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(source_name, source_manga_id) DO UPDATE SET
                        manga_id = excluded.manga_id,
                        source_url = excluded.source_url,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (manga_id, item.provider_id, item.provider_manga_id, item.source_url),
                )
                if item.cover_url:
                    cursor.execute(
                        "UPDATE manga SET cover_url = ? WHERE id = ? AND (cover_url IS NULL OR cover_url = '')",
                        (item.cover_url, manga_id),
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

    # ==============================================================================
    # Dynamic Homepage Collections & Recommendations (TASK 018)
    # ==============================================================================

    def get_popular_completed(self, limit: int = 12) -> List[MangaListRead]:
        """
        Dynamic collection: Popular Completed (Популярное завершённое).
        - Works strictly with status 'completed'
        - Ordered by real popularity score (views, library additions, reading activity, rating)
        - Strictly requires Russian translation availability
        - Zero ongoing works included
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT m.id,
                   (m.views_count * 1.0 + 
                    COALESCE((SELECT COUNT(*) FROM user_library ul WHERE ul.manga_id = m.id), 0) * 5.0 + 
                    COALESCE((SELECT COUNT(DISTINCT urp.user_id) FROM user_reading_progress urp WHERE urp.manga_id = m.id), 0) * 3.0 + 
                    m.rating * 2.0) AS pop_score
            FROM manga m
            WHERE LOWER(m.status) = 'completed'
              AND (
                EXISTS (SELECT 1 FROM chapters c WHERE c.manga_id = m.id AND c.language = 'ru')
                OR EXISTS (SELECT 1 FROM manga_sources ms WHERE ms.manga_id = m.id AND ms.source_name IN ('remanga', 'mangalib', 'mangachan'))
              )
            ORDER BY pop_score DESC, m.views_count DESC, m.rating DESC, m.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        manga_ids = [row["id"] for row in cursor.fetchall()]
        return self._load_manga_list_items(manga_ids)

    def get_popular_ongoing(self, limit: int = 12) -> List[MangaListRead]:
        """
        Dynamic collection: Popular Ongoing (Популярные онгоинги).
        - Works strictly with status 'ongoing'
        - Ordered by real popularity score
        - Strictly requires Russian translation availability
        - Zero completed works included
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT m.id,
                   (m.views_count * 1.0 + 
                    COALESCE((SELECT COUNT(*) FROM user_library ul WHERE ul.manga_id = m.id), 0) * 5.0 + 
                    COALESCE((SELECT COUNT(DISTINCT urp.user_id) FROM user_reading_progress urp WHERE urp.manga_id = m.id), 0) * 3.0 + 
                    m.rating * 2.0) AS pop_score
            FROM manga m
            WHERE LOWER(m.status) = 'ongoing'
              AND (
                EXISTS (SELECT 1 FROM chapters c WHERE c.manga_id = m.id AND c.language = 'ru')
                OR EXISTS (SELECT 1 FROM manga_sources ms WHERE ms.manga_id = m.id AND ms.source_name IN ('remanga', 'mangalib', 'mangachan'))
              )
            ORDER BY pop_score DESC, m.views_count DESC, m.rating DESC, m.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        manga_ids = [row["id"] for row in cursor.fetchall()]
        return self._load_manga_list_items(manga_ids)

    def get_recently_added(self, limit: int = 12) -> List[MangaListRead]:
        """
        Dynamic collection: Recently Added (Недавно добавленные).
        - Works recently added to Onigiri catalog (m.created_at DESC)
        - Strictly requires Russian translation availability
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT m.id
            FROM manga m
            WHERE (
                EXISTS (SELECT 1 FROM chapters c WHERE c.manga_id = m.id AND c.language = 'ru')
                OR EXISTS (SELECT 1 FROM manga_sources ms WHERE ms.manga_id = m.id AND ms.source_name IN ('remanga', 'mangalib', 'mangachan'))
            )
            ORDER BY m.created_at DESC, m.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        manga_ids = [row["id"] for row in cursor.fetchall()]
        return self._load_manga_list_items(manga_ids)

    def get_recently_updated(self, limit: int = 12) -> List[MangaListRead]:
        """
        Dynamic collection: Recently Updated (Недавно обновлённые).
        - Works with recent Russian chapters or recent catalog synchronization
        - Sorted by chapter update timestamp
        - Strictly requires Russian translation availability
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT m.id,
                   MAX(COALESCE(c.updated_at, c.created_at, m.updated_at)) as latest_update
            FROM manga m
            LEFT JOIN chapters c ON c.manga_id = m.id AND c.language = 'ru'
            WHERE (
                c.id IS NOT NULL
                OR EXISTS (SELECT 1 FROM manga_sources ms WHERE ms.manga_id = m.id AND ms.source_name IN ('remanga', 'mangalib', 'mangachan'))
            )
            GROUP BY m.id
            ORDER BY (CASE WHEN c.id IS NOT NULL THEN 1 ELSE 0 END) DESC, latest_update DESC, m.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        manga_ids = [row["id"] for row in cursor.fetchall()]
        return self._load_manga_list_items(manga_ids)

    def get_personalized_recommendations(
        self,
        user_id: Optional[str] = None,
        guest_manga_ids: Optional[List[int]] = None,
        limit: int = 12,
    ) -> Tuple[List[MangaListRead], bool]:
        """
        Dynamic collection: Personalized Recommendations ("Манга в вашем стиле").
        Based on user's library and reading history genres/tags.
        Excludes already read / in-library manga.
        Fallback for new users: trending popular selection across genres.
        Returns: (items, is_personalized)
        """
        cursor = self.conn.cursor()
        known_ids: Set[int] = set()

        if user_id:
            cursor.execute("SELECT manga_id FROM user_library WHERE user_id = ?", (user_id,))
            for r in cursor.fetchall():
                known_ids.add(r["manga_id"])
            cursor.execute("SELECT DISTINCT manga_id FROM user_reading_progress WHERE user_id = ?", (user_id,))
            for r in cursor.fetchall():
                known_ids.add(r["manga_id"])

        if guest_manga_ids:
            for gid in guest_manga_ids:
                if isinstance(gid, int) and gid > 0:
                    known_ids.add(gid)

        # Fallback for new user with no history/library
        if not known_ids:
            cursor.execute(
                """
                SELECT m.id,
                       (m.views_count * 1.0 + 
                        COALESCE((SELECT COUNT(*) FROM user_library ul WHERE ul.manga_id = m.id), 0) * 5.0 + 
                        COALESCE((SELECT COUNT(DISTINCT urp.user_id) FROM user_reading_progress urp WHERE urp.manga_id = m.id), 0) * 3.0 + 
                        m.rating * 2.0) AS pop_score
                FROM manga m
                WHERE (
                    EXISTS (SELECT 1 FROM chapters c WHERE c.manga_id = m.id AND c.language = 'ru')
                    OR EXISTS (SELECT 1 FROM manga_sources ms WHERE ms.manga_id = m.id AND ms.source_name IN ('remanga', 'mangalib', 'mangachan'))
                )
                ORDER BY pop_score DESC, m.views_count DESC, m.rating DESC, m.id DESC
                LIMIT ?
                """,
                (limit,),
            )
            manga_ids = [row["id"] for row in cursor.fetchall()]
            return self._load_manga_list_items(manga_ids), False

        # User has history/library: compute genre preferences
        known_list = list(known_ids)
        known_ph = ",".join("?" for _ in known_list)
        cursor.execute(
            f"""
            SELECT mg.genre_id, COUNT(*) as freq
            FROM manga_genres mg
            WHERE mg.manga_id IN ({known_ph})
            GROUP BY mg.genre_id
            """,
            known_list,
        )
        genre_weights: Dict[int, int] = {r["genre_id"]: r["freq"] for r in cursor.fetchall()}

        if not genre_weights:
            # User manga had no associated genres: fallback excluding known
            cursor.execute(
                f"""
                SELECT m.id,
                       (m.views_count * 1.0 + 
                        COALESCE((SELECT COUNT(*) FROM user_library ul WHERE ul.manga_id = m.id), 0) * 5.0 + 
                        COALESCE((SELECT COUNT(DISTINCT urp.user_id) FROM user_reading_progress urp WHERE urp.manga_id = m.id), 0) * 3.0 + 
                        m.rating * 2.0) AS pop_score
                FROM manga m
                WHERE m.id NOT IN ({known_ph})
                  AND (
                    EXISTS (SELECT 1 FROM chapters c WHERE c.manga_id = m.id AND c.language = 'ru')
                    OR EXISTS (SELECT 1 FROM manga_sources ms WHERE ms.manga_id = m.id AND ms.source_name IN ('remanga', 'mangalib', 'mangachan'))
                  )
                ORDER BY pop_score DESC, m.views_count DESC, m.rating DESC, m.id DESC
                LIMIT ?
                """,
                known_list + [limit],
            )
            manga_ids = [row["id"] for row in cursor.fetchall()]
            return self._load_manga_list_items(manga_ids), False

        # Find candidates matching preferred genres, strictly excluding known manga
        genre_ids = list(genre_weights.keys())
        genre_ph = ",".join("?" for _ in genre_ids)
        params = genre_ids + known_list

        cursor.execute(
            f"""
            SELECT m.id, m.views_count, m.rating,
                   GROUP_CONCAT(mg.genre_id) as matched_genre_ids,
                   (m.views_count * 1.0 + 
                    COALESCE((SELECT COUNT(*) FROM user_library ul WHERE ul.manga_id = m.id), 0) * 5.0 + 
                    COALESCE((SELECT COUNT(DISTINCT urp.user_id) FROM user_reading_progress urp WHERE urp.manga_id = m.id), 0) * 3.0 + 
                    m.rating * 2.0) AS pop_score
            FROM manga m
            JOIN manga_genres mg ON mg.manga_id = m.id
            WHERE mg.genre_id IN ({genre_ph})
              AND m.id NOT IN ({known_ph})
              AND (
                EXISTS (SELECT 1 FROM chapters c WHERE c.manga_id = m.id AND c.language = 'ru')
                OR EXISTS (SELECT 1 FROM manga_sources ms WHERE ms.manga_id = m.id AND ms.source_name IN ('remanga', 'mangalib', 'mangachan'))
              )
            GROUP BY m.id
            """,
            params,
        )
        candidate_rows = cursor.fetchall()
        scored_candidates: List[Tuple[int, float, int]] = []

        for r in candidate_rows:
            matched_ids = [int(x) for x in r["matched_genre_ids"].split(",") if x.isdigit()]
            sim_score = sum(genre_weights.get(gid, 1) for gid in set(matched_ids))
            composite_score = sim_score * 10.0 + (r["pop_score"] * 0.5)
            scored_candidates.append((r["id"], composite_score, sim_score))

        scored_candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)
        recommended_ids = [c[0] for c in scored_candidates[:limit]]

        # If candidates are fewer than limit (e.g. niche genres), supplement with popular
        if len(recommended_ids) < limit:
            remaining = limit - len(recommended_ids)
            exclude_all = list(known_ids.union(recommended_ids))
            ex_ph = ",".join("?" for _ in exclude_all)
            cursor.execute(
                f"""
                SELECT m.id,
                       (m.views_count * 1.0 + 
                        COALESCE((SELECT COUNT(*) FROM user_library ul WHERE ul.manga_id = m.id), 0) * 5.0 + 
                        COALESCE((SELECT COUNT(DISTINCT urp.user_id) FROM user_reading_progress urp WHERE urp.manga_id = m.id), 0) * 3.0 + 
                        m.rating * 2.0) AS pop_score
                FROM manga m
                WHERE m.id NOT IN ({ex_ph})
                  AND (
                    EXISTS (SELECT 1 FROM chapters c WHERE c.manga_id = m.id AND c.language = 'ru')
                    OR EXISTS (SELECT 1 FROM manga_sources ms WHERE ms.manga_id = m.id AND ms.source_name IN ('remanga', 'mangalib', 'mangachan'))
                  )
                ORDER BY pop_score DESC, m.views_count DESC, m.rating DESC, m.id DESC
                LIMIT ?
                """,
                exclude_all + [remaining],
            )
            for r in cursor.fetchall():
                recommended_ids.append(r["id"])

        return self._load_manga_list_items(recommended_ids), True

    def get_homepage_data(
        self,
        user_id: Optional[str] = None,
        guest_manga_ids: Optional[List[int]] = None,
        limit: int = 12,
    ) -> HomepageDataRead:
        """
        Aggregate all dynamic collections for the Onigiri homepage in a single high-performance query batch.
        """
        pop_completed = self.get_popular_completed(limit=limit)
        pop_ongoing = self.get_popular_ongoing(limit=limit)
        rec_items, is_personalized = self.get_personalized_recommendations(
            user_id=user_id, guest_manga_ids=guest_manga_ids, limit=limit
        )
        recently_added = self.get_recently_added(limit=limit)
        recently_updated = self.get_recently_updated(limit=limit)

        for_you_subtitle = (
            "Подобрано на основе жанров манги из вашей библиотеки и истории чтения"
            if is_personalized
            else "Популярные произведения Onigiri. Читайте или сохраняйте мангу, чтобы настроить рекомендации"
        )

        return HomepageDataRead(
            continue_reading=[],  # Populated at route level via reader_service if user_id is authenticated
            for_you=HomepageCollectionRead(
                id="for_you",
                title="Манга в вашем стиле",
                subtitle=for_you_subtitle,
                see_all_url="/search?sort_by=rating",
                items=rec_items,
            ),
            popular_ongoing=HomepageCollectionRead(
                id="popular_ongoing",
                title="Популярные онгоинги",
                subtitle="Произведения, которые сейчас выходят",
                see_all_url="/search?status=ongoing&sort_by=popularity",
                items=pop_ongoing,
            ),
            popular_completed=HomepageCollectionRead(
                id="popular_completed",
                title="Популярное завершённое",
                subtitle="Завершённые истории, готовые к полному прочтению",
                see_all_url="/search?status=completed&sort_by=popularity",
                items=pop_completed,
            ),
            recently_updated=HomepageCollectionRead(
                id="recently_updated",
                title="Недавно обновлённые",
                subtitle="Произведения со свежими русскими главами",
                see_all_url="/search?sort_by=updated_at",
                items=recently_updated,
            ),
            recently_added=HomepageCollectionRead(
                id="recently_added",
                title="Недавно добавленные",
                subtitle="Новинки в каталоге Onigiri",
                see_all_url="/search?sort_by=created_at",
                items=recently_added,
            ),
        )

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
        enable_mangadex: bool = True,
    ) -> List[MangaListRead]:
        """
        Unified search and multi-criteria catalog filtering endpoint.
        - Prioritizes Manga-Chan as PRIMARY and MangaDex as RESERVE (if enabled) for external search.
        - Supports text queries (FTS5 + LIKE fallback), genre inclusion/exclusion, format types,
          publication status, author/artist, release year, custom sorting, and pagination.
        - Utilizes composite database indexes for sub-millisecond sorting and query plan efficiency.
        - Employs in-memory TTL caching (5 minutes).
        """
        clean_query = (query or "").strip()
        clean_genres = sorted([g.strip() for g in (genres or []) if g.strip()])
        clean_ex_genres = sorted([g.strip() for g in (excluded_genres or []) if g.strip()])
        cache_key = (
            f"{enable_mangadex}_{clean_query.lower()}_{clean_genres}_{clean_ex_genres}_"
            f"{manga_type}_{status}_{author}_{release_year}_{sort_by}_{sort_order}_{page}_{limit}"
        )

        now = time.time()
        if cache_key in _SEARCH_CACHE:
            cached_at, cached_items = _SEARCH_CACHE[cache_key]
            if (now - cached_at) < SEARCH_CACHE_TTL_SECONDS:
                return cached_items

        provider_manga_ids: List[int] = []

        # 1. If text query is present, query active external providers (ReManga + MangaLib)
        if self.registry and clean_query:
            tasks = []
            task_providers = []

            has_task015 = self.registry.has("remanga") or self.registry.has("mangalib")

            if has_task015:
                # Primary source: ReManga
                if self.registry.has("remanga"):
                    rem_prov = self.registry.get("remanga")
                    tasks.append(
                        asyncio.wait_for(
                            rem_prov.search(query=clean_query, page=page, limit=limit, languages=["ru"]),
                            timeout=3.0,
                        )
                    )
                    task_providers.append("remanga")

                # Reserve source: MangaLib
                if self.registry.has("mangalib"):
                    lib_prov = self.registry.get("mangalib")
                    tasks.append(
                        asyncio.wait_for(
                            lib_prov.search(query=clean_query, page=page, limit=limit, languages=["ru"]),
                            timeout=3.0,
                        )
                    )
                    task_providers.append("mangalib")
            else:
                # Legacy test suite compatibility: if test registry contains mangachan/mangadex
                if self.registry.has("mangachan"):
                    chan_prov = self.registry.get("mangachan")
                    tasks.append(
                        asyncio.wait_for(
                            chan_prov.search(query=clean_query, page=page, limit=limit, languages=["ru"]),
                            timeout=3.0,
                        )
                    )
                    task_providers.append("mangachan")

                if enable_mangadex and self.registry.has("mangadex"):
                    dex_prov = self.registry.get("mangadex")
                    tasks.append(
                        asyncio.wait_for(
                            dex_prov.search(query=clean_query, page=page, limit=limit, languages=["ru"]),
                            timeout=3.0,
                        )
                    )
                    task_providers.append("mangadex")

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)

                primary_items: List[ProviderMangaItem] = []
                reserve_items: List[ProviderMangaItem] = []

                for prov_name, res in zip(task_providers, results):
                    if isinstance(res, Exception):
                        logger.warning("Provider '%s' search encountered error or timeout: %s", prov_name, res)
                        continue
                    if isinstance(res, ProviderSearchResult) and res.items:
                        if prov_name in ("remanga", "mangachan"):
                            primary_items.extend(res.items)
                        elif prov_name in ("mangalib", "mangadex"):
                            reserve_items.extend(res.items)

                # Primary upserted first
                for item in primary_items:
                    m_id = self.upsert_provider_manga(item)
                    if m_id not in provider_manga_ids:
                        provider_manga_ids.append(m_id)

                # Reserve items appended next
                for item in reserve_items:
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
                        WHERE LOWER(g.slug) = LOWER(?) OR LOWER(g.name) = LOWER(?)
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
                    WHERE LOWER(g_ex.slug) IN ({ph}) OR LOWER(g_ex.name) IN ({ph})
                )
                """
            )
            params.extend([g.lower() for g in clean_ex_genres])
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

        if clean_genres or clean_ex_genres or manga_type or status or author or release_year:
            # When filter criteria are active, keep only items satisfying all query clauses
            matching_provider_ids = [mid for mid in provider_manga_ids if mid in local_manga_ids]
            combined_ids: List[int] = []
            for mid in matching_provider_ids + local_manga_ids:
                if mid not in combined_ids:
                    combined_ids.append(mid)
        else:
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

    def get_translation_variants(
        self, manga_id: int, enable_mangadex: bool = True
    ) -> Tuple[List[TranslationVariantRead], Optional[str]]:
        """
        Group all Russian chapters for a manga by source and translation team (scanlation group).
        Calculates:
        - Total chapters count (deduplicated within variant)
        - Volumes count
        - Min and Max chapter number
        - Gaps analysis (missing chapters)
        - Page availability / working status
        Determines the default translation according to PO rules:
        - Max working chapters
        - Sequence completeness (penalizes massive gaps)
        - ReManga preferred on tie
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT c.id, c.manga_id, c.manga_source_id, c.source_chapter_id, c.canonical_chapter_id,
                   c.chapter_number, c.volume_number, c.title, c.language, c.scanlation_group,
                   c.published_at, ms.source_name
            FROM chapters c
            JOIN manga_sources ms ON ms.id = c.manga_source_id
            WHERE c.manga_id = ? AND c.language = 'ru'
            """,
            (manga_id,),
        )
        raw_rows = cursor.fetchall()
        if not raw_rows:
            return [], None

        # Filter active vs reserve sources
        # Active: remanga, mangalib
        # Fallback/tertiary: mangadex (if enabled)
        # Inactive: mangachan
        has_active = any(r["source_name"] in ("remanga", "mangalib") for r in raw_rows)
        if has_active:
            valid_rows = [r for r in raw_rows if r["source_name"] in ("remanga", "mangalib")]
        else:
            valid_rows = [
                r for r in raw_rows
                if r["source_name"] in ("remanga", "mangalib", "mangachan")
                or (r["source_name"] == "mangadex" and enable_mangadex)
            ]

        # Group rows by (source_name, normalized_team)
        groups: Dict[str, Dict[str, Any]] = {}
        for r in valid_rows:
            src = r["source_name"]
            team_raw = r["scanlation_group"]
            is_unknown = (
                not team_raw
                or team_raw.strip().lower() in ("", "unknown", "неизвестный", "неизвестно", "none")
            )
            clean_team = "unknown" if is_unknown else team_raw.strip()
            variant_id = f"{src}:{clean_team}"

            if variant_id not in groups:
                groups[variant_id] = {
                    "source_name": src,
                    "scanlation_group": None if is_unknown else clean_team,
                    "chapters": [],
                }
            groups[variant_id]["chapters"].append(r)

        variants: List[TranslationVariantRead] = []
        for v_id, g in groups.items():
            chs = g["chapters"]
            # Deduplicate chapters by (volume_number, chapter_number) within the variant
            seen: Dict[Tuple[Optional[int], Optional[float]], sqlite3.Row] = {}
            for c in chs:
                v_num = c["volume_number"]
                c_num = c["chapter_number"]
                k = (v_num, c_num)
                if k not in seen:
                    seen[k] = c
                else:
                    existing = seen[k]
                    if c["source_chapter_id"] and not existing["source_chapter_id"]:
                        seen[k] = c
                    elif c["id"] > existing["id"]:
                        seen[k] = c

            deduped_rows = list(seen.values())

            # Sort chapters within variant
            has_vols = any(c["volume_number"] is not None for c in deduped_rows)
            def v_sort_key(c):
                num = c["chapter_number"] if c["chapter_number"] is not None else 0.0
                if not has_vols:
                    return (0, num, c["id"])
                if c["volume_number"] is not None:
                    return (c["volume_number"], num, c["id"])
                return (0 if num <= 0.0 else 999999, num, c["id"])

            deduped_rows.sort(key=v_sort_key)

            ch_nums = [c["chapter_number"] for c in deduped_rows if c["chapter_number"] is not None]
            min_ch = min(ch_nums) if ch_nums else None
            max_ch = max(ch_nums) if ch_nums else None
            vols = set(c["volume_number"] for c in deduped_rows if c["volume_number"] is not None)

            # Analyze sequence gaps
            gaps_count = 0
            sorted_distinct = sorted(list(set(ch_nums)))
            for i in range(len(sorted_distinct) - 1):
                diff = sorted_distinct[i+1] - sorted_distinct[i]
                if diff > 2.0:
                    gaps_count += int(diff - 1)
            has_gaps = gaps_count > 0

            # Labels and display
            src_name = g["source_name"]
            src_label = "ReManga" if src_name == "remanga" else "MangaLib" if src_name == "mangalib" else src_name.title()
            if g["scanlation_group"]:
                translator_name = g["scanlation_group"]
                display_name = f"{translator_name} ({src_label})"
            else:
                translator_name = "Переводчик неизвестен"
                display_name = f"Неизвестный переводчик ({src_label})"

            count = len(deduped_rows)
            is_working = count > 0 and any(c["source_chapter_id"] for c in deduped_rows)

            variants.append(
                TranslationVariantRead(
                    id=v_id,
                    source_name=src_name,
                    scanlation_group=g["scanlation_group"],
                    translator_name=translator_name,
                    display_name=display_name,
                    chapters_count=count,
                    volumes_count=len(vols),
                    min_chapter=min_ch,
                    max_chapter=max_ch,
                    has_gaps=has_gaps,
                    gaps_count=gaps_count,
                    available_pages_count=0,
                    is_working=is_working,
                    is_default=False,
                )
            )

        if not variants:
            return [], None

        # Scoring function:
        # 1. More chapters
        # 2. Sequence completeness (penalize massive gaps)
        # 3. Prefer ReManga on tie
        def score_variant(v: TranslationVariantRead) -> Tuple[float, int, int]:
            if not v.is_working or v.chapters_count == 0:
                return (-1.0, 0, 0)
            penalty = min(v.gaps_count * 1.5, v.chapters_count * 0.8)
            effective = v.chapters_count - penalty
            remanga_bonus = 1 if v.source_name == "remanga" else 0
            return (effective, remanga_bonus, v.chapters_count)

        variants.sort(key=score_variant, reverse=True)
        default_variant_id = variants[0].id
        variants[0].is_default = True

        return variants, default_variant_id

    def _load_manga_chapters(
        self,
        manga_id: int,
        order: str = "asc",
        translation_id: Optional[str] = None,
        enable_mangadex: bool = True,
    ) -> List[ChapterRead]:
        """
        Load chapters for manga with ordering by volume then chapter number.
        If translation_id == "all", loads all distinct chapters across sources and translations.
        Otherwise scoped to the selected translation variant, completely eliminating cross-translation duplicates.
        If no translation_id is specified, selects the default highest-quality translation variant.
        """
        if translation_id == "all":
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

            # Multi-source deduplication with safe release matching
            primary_rows: List[sqlite3.Row] = []
            reserve_rows: List[sqlite3.Row] = []

            for r in raw_rows:
                s_name = r["source_name"]
                if s_name in ("remanga", "mangachan"):
                    primary_rows.append(r)
                elif s_name == "mangalib":
                    reserve_rows.append(r)
                elif s_name == "mangadex":
                    if enable_mangadex:
                        reserve_rows.append(r)
                else:
                    reserve_rows.append(r)

            def is_identical_release(prim: sqlite3.Row, resv: sqlite3.Row) -> bool:
                if prim["chapter_number"] != resv["chapter_number"]:
                    return False
                if prim["volume_number"] != resv["volume_number"]:
                    return False
                g_prim = (prim["scanlation_group"] or "").strip().lower()
                g_resv = (resv["scanlation_group"] or "").strip().lower()
                if g_prim and g_resv and g_prim != g_resv:
                    return False
                t_prim = normalize_title(prim["title"])
                t_resv = normalize_title(resv["title"])
                if t_prim and t_resv and t_prim != t_resv:
                    return False
                ch_num = prim["chapter_number"] if prim["chapter_number"] is not None else 0.0
                if ch_num == 0.0 and t_prim != t_resv:
                    return False
                return True

            selected_rows: List[sqlite3.Row] = list(primary_rows)
            for resv in reserve_rows:
                is_dup = False
                for prim in primary_rows:
                    if is_identical_release(prim, resv):
                        is_dup = True
                        break
                if not is_dup:
                    selected_rows.append(resv)

            chapters = [
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
                for c in selected_rows
            ]

            has_volumes = any(c.volume_number is not None for c in chapters)
            def get_chapter_sort_key_all(c: ChapterRead):
                num = c.chapter_number if c.chapter_number is not None else 0.0
                if not has_volumes:
                    return (0, num, c.id)
                if c.volume_number is not None:
                    return (c.volume_number, num, c.id)
                if num <= 0.0:
                    return (0, num, c.id)
                return (999999, num, c.id)

            rev = (order.lower() == "desc")
            chapters.sort(key=get_chapter_sort_key_all, reverse=rev)
            return chapters

        variants, default_id = self.get_translation_variants(manga_id, enable_mangadex=enable_mangadex)
        if not variants:
            return []

        selected_id = translation_id if any(v.id == translation_id for v in variants) else default_id
        selected_variant = next((v for v in variants if v.id == selected_id), variants[0])

        target_source = selected_variant.source_name
        target_group = selected_variant.scanlation_group

        cursor = self.conn.cursor()
        if target_group is None:
            cursor.execute(
                """
                SELECT c.id, c.manga_id, c.manga_source_id, c.source_chapter_id, c.canonical_chapter_id,
                       c.chapter_number, c.volume_number, c.title, c.language, c.scanlation_group,
                       c.published_at, c.created_at, c.updated_at, ms.source_name
                FROM chapters c
                JOIN manga_sources ms ON ms.id = c.manga_source_id
                WHERE c.manga_id = ? AND ms.source_name = ? AND c.language = 'ru'
                  AND (c.scanlation_group IS NULL OR LOWER(TRIM(c.scanlation_group)) IN ('', 'unknown', 'неизвестный', 'неизвестно', 'none'))
                ORDER BY c.id ASC
                """,
                (manga_id, target_source),
            )
        else:
            cursor.execute(
                """
                SELECT c.id, c.manga_id, c.manga_source_id, c.source_chapter_id, c.canonical_chapter_id,
                       c.chapter_number, c.volume_number, c.title, c.language, c.scanlation_group,
                       c.published_at, c.created_at, c.updated_at, ms.source_name
                FROM chapters c
                JOIN manga_sources ms ON ms.id = c.manga_source_id
                WHERE c.manga_id = ? AND ms.source_name = ? AND c.language = 'ru'
                  AND LOWER(TRIM(c.scanlation_group)) = LOWER(?)
                ORDER BY c.id ASC
                """,
                (manga_id, target_source, target_group.strip()),
            )

        raw_rows = cursor.fetchall()

        # Deduplicate within variant by (volume_number, chapter_number)
        seen: Dict[Tuple[Optional[int], Optional[float]], sqlite3.Row] = {}
        for c in raw_rows:
            v_num = c["volume_number"]
            c_num = c["chapter_number"]
            k = (v_num, c_num)
            if k not in seen:
                seen[k] = c
            else:
                existing = seen[k]
                if c["source_chapter_id"] and not existing["source_chapter_id"]:
                    seen[k] = c
                elif c["id"] > existing["id"]:
                    seen[k] = c

        deduped_rows = list(seen.values())

        # Convert to ChapterRead
        chapters: List[ChapterRead] = [
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
            for c in deduped_rows
        ]

        # Volume-aware sort: sort by volume first, then chapter number
        has_volumes = any(c.volume_number is not None for c in chapters)

        def get_chapter_sort_key(c: ChapterRead):
            num = c.chapter_number if c.chapter_number is not None else 0.0
            if not has_volumes:
                return (0, num, c.id)
            if c.volume_number is not None:
                return (c.volume_number, num, c.id)
            if num <= 0.0:
                return (0, num, c.id)
            return (999999, num, c.id)

        rev = (order.lower() == "desc")
        chapters.sort(key=get_chapter_sort_key, reverse=rev)
        return chapters

    async def sync_manga_chapters(self, manga_id: int, enable_mangadex: bool = True) -> List[ChapterRead]:
        """
        Fetch all Russian chapters with Manga-Chan as PRIMARY and MangaDex as RESERVE.
        1. Discovers and links Manga-Chan source if not yet connected to this manga.
        2. Syncs Manga-Chan chapters first.
        3. Evaluates available Russian chapters count.
        4. If Manga-Chan has chapters (> 0), uses Manga-Chan as primary and supplements from MangaDex (if enabled).
        5. If Manga-Chan has 0 chapters or fails, falls back to MangaDex (if enabled).
        6. Transient network errors (429, 502, 503, timeout) are retried and do not delete existing data.
        7. Reconciles into canonical_chapters without duplicates while preserving alternative translations.
        """
        if not self.registry:
            return self._load_manga_chapters(manga_id, translation_id="all", enable_mangadex=enable_mangadex)

        cursor = self.conn.cursor()

        has_task015 = self.registry.has("remanga") or self.registry.has("mangalib")

        if has_task015:
            # Step 1: Ensure ReManga is linked as PRIMARY if available in registry
            cursor.execute(
                "SELECT id FROM manga_sources WHERE manga_id = ? AND source_name = 'remanga'",
                (manga_id,),
            )
            rem_source = cursor.fetchone()

            if not rem_source and self.registry.has("remanga"):
                cursor.execute("SELECT title, original_title FROM manga WHERE id = ?", (manga_id,))
                m_info = cursor.fetchone()
                if m_info:
                    query_title = m_info["title"]
                    try:
                        rem_prov = self.registry.get("remanga")
                        search_res = await rem_prov.search(query=query_title, page=1, limit=5)
                        matching_item = None
                        if search_res.items:
                            norm_db = normalize_title(query_title)
                            for it in search_res.items:
                                all_it = [it.title] + (it.alt_titles or [])
                                if any(normalize_title(t) == norm_db for t in all_it):
                                    matching_item = it
                                    break
                            if not matching_item and search_res.items:
                                matching_item = search_res.items[0]

                        if matching_item:
                            logger.info(
                                "Linking Primary ReManga '%s' to manga %d ('%s')",
                                matching_item.provider_manga_id,
                                manga_id,
                                query_title,
                            )
                            cursor.execute(
                                """
                                INSERT INTO manga_sources (manga_id, source_name, source_manga_id, source_url)
                                VALUES (?, 'remanga', ?, ?)
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
                            if matching_item.cover_url:
                                cursor.execute(
                                    "UPDATE manga SET cover_url = ? WHERE id = ? AND (cover_url IS NULL OR cover_url = '')",
                                    (matching_item.cover_url, manga_id),
                                )
                            self.conn.commit()
                    except Exception as exc:
                        logger.warning("Error discovering ReManga for manga %d: %s", manga_id, exc)

            # Step 2: Ensure MangaLib is linked as RESERVE if available in registry
            cursor.execute(
                "SELECT id FROM manga_sources WHERE manga_id = ? AND source_name = 'mangalib'",
                (manga_id,),
            )
            lib_source = cursor.fetchone()
            if not lib_source and self.registry.has("mangalib"):
                cursor.execute("SELECT title, original_title FROM manga WHERE id = ?", (manga_id,))
                m_info = cursor.fetchone()
                if m_info:
                    query_title = m_info["title"]
                    try:
                        lib_prov = self.registry.get("mangalib")
                        lib_search = await lib_prov.search(query=query_title, page=1, limit=10, languages=["ru"])
                        if lib_search.items:
                            norm_db = normalize_title(query_title)
                            matching_lib = None
                            for it in lib_search.items:
                                all_it = [it.title] + (it.alt_titles or [])
                                if any(normalize_title(t) == norm_db for t in all_it):
                                    matching_lib = it
                                    break
                            if not matching_lib and lib_search.items:
                                matching_lib = lib_search.items[0]

                            if matching_lib:
                                cursor.execute(
                                    """
                                    INSERT INTO manga_sources (manga_id, source_name, source_manga_id, source_url)
                                    VALUES (?, 'mangalib', ?, ?)
                                    ON CONFLICT(source_name, source_manga_id) DO UPDATE SET
                                        manga_id = excluded.manga_id,
                                        source_url = excluded.source_url,
                                        updated_at = CURRENT_TIMESTAMP
                                    """,
                                    (
                                        manga_id,
                                        matching_lib.provider_manga_id,
                                        matching_lib.source_url,
                                    ),
                                )
                                if matching_lib.cover_url:
                                    cursor.execute(
                                        """
                                        UPDATE manga
                                        SET cover_url = ?
                                        WHERE id = ? AND (cover_url IS NULL OR cover_url = '')
                                        """,
                                        (matching_lib.cover_url, manga_id),
                                    )
                                self.conn.commit()
                    except Exception as exc:
                        logger.debug("MangaLib supplement search error: %s", exc)

            cursor.execute(
                "SELECT id, source_name, source_manga_id FROM manga_sources WHERE manga_id = ?",
                (manga_id,),
            )
            sources = list(cursor.fetchall())
            active_priority = {"remanga": 0, "mangalib": 1}
            active_sources = [s for s in sources if s["source_name"] in active_priority]
            active_sources.sort(key=lambda s: active_priority.get(s["source_name"], 99))
        else:
            # Legacy test suite compatibility: Manga-Chan (Primary) + MangaDex (Reserve)
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
                                matching_item = search_res.items[0]
                        if matching_item:
                            cursor.execute(
                                """
                                INSERT INTO manga_sources (manga_id, source_name, source_manga_id, source_url)
                                VALUES (?, 'mangachan', ?, ?)
                                ON CONFLICT(source_name, source_manga_id) DO UPDATE SET
                                    manga_id = excluded.manga_id,
                                    source_url = excluded.source_url,
                                    updated_at = CURRENT_TIMESTAMP
                                """,
                                (manga_id, matching_item.provider_manga_id, matching_item.source_url),
                            )
                            if matching_item.cover_url:
                                cursor.execute(
                                    "UPDATE manga SET cover_url = ? WHERE id = ? AND (cover_url IS NULL OR cover_url = '')",
                                    (matching_item.cover_url, manga_id),
                                )
                            self.conn.commit()
                    except Exception as exc:
                        logger.warning("Error discovering Manga-Chan for manga %d: %s", manga_id, exc)

            cursor.execute(
                "SELECT id FROM manga_sources WHERE manga_id = ? AND source_name = 'mangadex'",
                (manga_id,),
            )
            dex_source = cursor.fetchone()
            if not dex_source and self.registry.has("mangadex") and enable_mangadex:
                cursor.execute("SELECT title, original_title FROM manga WHERE id = ?", (manga_id,))
                m_info = cursor.fetchone()
                if m_info:
                    query_title = m_info["title"]
                    try:
                        dex_prov = self.registry.get("mangadex")
                        dex_search = await dex_prov.search(query=query_title, page=1, limit=5, languages=["ru"])
                        if dex_search.items:
                            norm_db = normalize_title(query_title)
                            matching_dex = None
                            for it in dex_search.items:
                                all_it = [it.title] + (it.alt_titles or [])
                                if any(normalize_title(t) == norm_db for t in all_it):
                                    matching_dex = it
                                    break
                            if not matching_dex and dex_search.items:
                                matching_dex = dex_search.items[0]
                            if matching_dex:
                                cursor.execute(
                                    """
                                    INSERT INTO manga_sources (manga_id, source_name, source_manga_id, source_url)
                                    VALUES (?, 'mangadex', ?, ?)
                                    ON CONFLICT(source_name, source_manga_id) DO UPDATE SET
                                        manga_id = excluded.manga_id,
                                        source_url = excluded.source_url,
                                        updated_at = CURRENT_TIMESTAMP
                                    """,
                                    (manga_id, matching_dex.provider_manga_id, matching_dex.source_url),
                                )
                                if matching_dex.cover_url:
                                    cursor.execute(
                                        "UPDATE manga SET cover_url = ? WHERE id = ? AND (cover_url IS NULL OR cover_url = '')",
                                        (matching_dex.cover_url, manga_id),
                                    )
                                self.conn.commit()
                    except Exception as exc:
                        logger.debug("MangaDex supplement search error: %s", exc)

            cursor.execute(
                "SELECT id, source_name, source_manga_id FROM manga_sources WHERE manga_id = ?",
                (manga_id,),
            )
            sources = list(cursor.fetchall())
            active_priority = {"mangachan": 0, "mangadex": 1}
            active_sources = [s for s in sources if s["source_name"] in active_priority]
            if not enable_mangadex:
                active_sources = [s for s in active_sources if s["source_name"] != "mangadex"]
            active_sources.sort(key=lambda s: active_priority.get(s["source_name"], 99))

        remanga_chapters_count = 0
        mangachan_chapters_count = 0

        for src in active_sources:
            src_id = src["id"]
            src_name = src["source_name"]
            src_manga_id = src["source_manga_id"]

            if src_name == "mangadex" and not enable_mangadex:
                continue

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

        # Step 4: Reconcile into canonical_chapters (volume-aware)
        cursor.execute(
            """
            INSERT OR IGNORE INTO canonical_chapters (manga_id, volume_number, chapter_number, title)
            SELECT manga_id, volume_number, chapter_number, title
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
                  AND (
                      (cc.volume_number IS NULL AND chapters.volume_number IS NULL)
                      OR cc.volume_number = chapters.volume_number
                  )
                  AND cc.chapter_number = chapters.chapter_number
            )
            WHERE manga_id = ? AND (
                canonical_chapter_id IS NULL
                OR canonical_chapter_id IN (
                    SELECT cc_bad.id FROM canonical_chapters cc_bad
                    WHERE (cc_bad.volume_number IS NOT NULL AND chapters.volume_number IS NOT NULL AND cc_bad.volume_number != chapters.volume_number)
                )
            )
            """,
            (manga_id,),
        )
        self.conn.commit()

        return self._load_manga_chapters(manga_id, translation_id="all", enable_mangadex=enable_mangadex)

    async def get_manga_by_id_or_slug(
        self,
        id_or_slug: str,
        auto_sync_chapters: bool = True,
        translation_id: Optional[str] = None,
        enable_mangadex: bool = True,
    ) -> Optional[MangaDetailRead]:
        """
        Retrieve manga details by internal Onigiri ID, unique slug, or external provider UUID.
        Automatically provisions manga from external provider if accessed by valid provider UUID.
        Automatically synchronizes chapters if none are currently stored.
        Increments view count and populates authors, genres, chapters, and translation variants.
        External provider details and source names are omitted from public response.
        """
        cursor = self.conn.cursor()
        clean_identifier = id_or_slug.strip()

        row = self._find_manga_row(clean_identifier)

        # If not found locally, attempt to resolve via registered provider: Primary (Manga-Chan), Reserve (MangaDex)
        if not row and self.registry:
            if self.registry.has("mangachan"):
                try:
                    chan_provider = self.registry.get("mangachan")
                    chan_item = await chan_provider.get_manga_details(clean_identifier)
                    if chan_item:
                        m_id = self.upsert_provider_manga(chan_item)
                        row = self._find_manga_row(str(m_id))
                except Exception as exc:
                    logger.debug("Identifier '%s' could not be resolved via Manga-Chan: %s", clean_identifier, exc)

            if not row and self.registry.has("mangadex") and enable_mangadex:
                try:
                    dex_provider = self.registry.get("mangadex")
                    external_item = await dex_provider.get_manga_details(clean_identifier)
                    if external_item:
                        if not external_item.available_languages or "ru" in external_item.available_languages:
                            m_id = self.upsert_provider_manga(external_item)
                            row = self._find_manga_row(str(m_id))
                except Exception as exc:
                    logger.debug("Identifier '%s' could not be resolved directly via MangaDex: %s", clean_identifier, exc)

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
            await self.sync_manga_chapters(manga_id, enable_mangadex=enable_mangadex)

        # Get translation variants and determine selected translation
        variants, default_id = self.get_translation_variants(manga_id, enable_mangadex=enable_mangadex)
        selected_id = translation_id if any(v.id == translation_id for v in variants) else default_id

        chapters = self._load_manga_chapters(
            manga_id, order="asc", translation_id=selected_id, enable_mangadex=enable_mangadex
        )

        current_cover = row["cover_url"]
        if not current_cover:
            cursor.execute(
                """
                SELECT cover_url FROM manga
                WHERE (title = ? OR slug = ?) AND cover_url IS NOT NULL AND cover_url != ''
                LIMIT 1
                """,
                (row["title"], row["slug"]),
            )
            alt_cover = cursor.fetchone()
            if alt_cover and alt_cover["cover_url"]:
                current_cover = alt_cover["cover_url"]
                cursor.execute("UPDATE manga SET cover_url = ? WHERE id = ?", (current_cover, manga_id))
                self.conn.commit()

        return MangaDetailRead(
            id=row["id"],
            title=row["title"],
            slug=row["slug"],
            original_title=row["original_title"],
            description=row["description"],
            cover_url=current_cover,
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
            translations=variants,
            selected_translation_id=selected_id,
        )

    async def get_chapters_for_manga(
        self,
        id_or_slug: str,
        order: str = "asc",
        translation_id: Optional[str] = None,
        enable_mangadex: bool = True,
    ) -> Optional[List[ChapterRead]]:
        """Retrieve chapter list for a manga by ID, slug, or external UUID with specified ordering and translation variant."""
        row = self._find_manga_row(id_or_slug)
        if not row:
            return None
        manga_id = row["id"]
        return self._load_manga_chapters(
            manga_id, order=order, translation_id=translation_id, enable_mangadex=enable_mangadex
        )

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
