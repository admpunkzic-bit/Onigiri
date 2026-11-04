"""
Seed script to populate dummy manga catalog data for development and testing.
Idempotent: safe to run multiple times without duplicating data.
"""

import logging
import sqlite3
import sys
from pathlib import Path

# Ensure backend root is in sys.path when executed directly as script
if __package__ is None or __package__ == "":
    backend_dir = Path(__file__).resolve().parent.parent
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    from database.connection import get_connection, init_db
else:
    from database.connection import get_connection, init_db

logger = logging.getLogger(__name__)

# Sample dummy data structure
SAMPLE_GENRES = [
    ("Сёнэн", "shonen"),
    ("Приключения", "adventure"),
    ("Фэнтези", "fantasy"),
    ("Киберпанк", "cyberpunk"),
    ("Боевик", "action"),
    ("Фантастика", "sci-fi"),
    ("Повседневность", "slice-of-life"),
    ("Комедия", "comedy"),
    ("Сверхъестественное", "supernatural"),
    ("Космоопера", "space-opera"),
]

SAMPLE_AUTHORS = [
    "Kenji Sato",
    "Aoi Tanaka",
    "Hiroshi Takahashi",
    "Yumi Hoshino",
    "Takeshi Vance",
]

SAMPLE_MANGA = [
    {
        "title": "Хроники Онигири",
        "slug": "onigiri-chronicles",
        "original_title": "Onigiri Chronicles",
        "description": "Эпическое кулинарное путешествие юного повара по волшебному миру Онигири, где древние рецепты обладают магической силой.",
        "cover_url": "https://placehold.co/400x600/e2e8f0/1e293b.png?text=Onigiri+Chronicles",
        "banner_url": "https://placehold.co/1200x400/e2e8f0/1e293b.png?text=Onigiri+Banner",
        "status": "ongoing",
        "type": "manga",
        "release_year": 2024,
        "rating": 9.2,
        "views_count": 12450,
        "genres": ["shonen", "adventure", "fantasy"],
        "authors": [("Kenji Sato", "author"), ("Aoi Tanaka", "artist")],
        "sources": [
            {
                "source_name": "mangadex",
                "source_manga_id": "md-onigiri-001",
                "source_url": "https://mangadex.org/title/dummy-onigiri-001",
                "chapters": [
                    {
                        "chapter_number": 1.0,
                        "volume_number": 1,
                        "title": "Начало пути",
                        "pages": 3,
                    },
                    {
                        "chapter_number": 2.0,
                        "volume_number": 1,
                        "title": "Тайный рецепт рисового шарика",
                        "pages": 4,
                    },
                    {
                        "chapter_number": 2.5,
                        "volume_number": 1,
                        "title": "Спецвыпуск: Кулинарная битва",
                        "pages": 2,
                    },
                    {
                        "chapter_number": 3.0,
                        "volume_number": 1,
                        "title": "Шёпот древнего риса",
                        "pages": 3,
                    },
                ],
            },
            {
                "source_name": "local_seed",
                "source_manga_id": "local-onigiri-001",
                "source_url": "https://onigiri.punk.uz/manga/onigiri-chronicles",
                "chapters": [
                    {
                        "chapter_number": 1.0,
                        "volume_number": 1,
                        "title": "Начало пути (Local HQ)",
                        "pages": 3,
                    },
                ],
            },
        ],
    },
    {
        "title": "Токийский Киберраннер",
        "slug": "tokyo-cyber-runner",
        "original_title": "Tokyo Cyber Runner",
        "description": "В залитом неоном Токио 2099 года курьер данных берется за доставку чипа с запрещенным ИИ, спасаясь от мегакорпораций.",
        "cover_url": "https://placehold.co/400x600/0f172a/38bdf8.png?text=Cyber+Runner",
        "banner_url": "https://placehold.co/1200x400/0f172a/38bdf8.png?text=Cyber+Runner+Banner",
        "status": "ongoing",
        "type": "manhwa",
        "release_year": 2025,
        "rating": 8.8,
        "views_count": 8900,
        "genres": ["cyberpunk", "action", "sci-fi"],
        "authors": [("Hiroshi Takahashi", "author_artist")],
        "sources": [
            {
                "source_name": "mangadex",
                "source_manga_id": "md-cyber-002",
                "source_url": "https://mangadex.org/title/dummy-cyber-002",
                "chapters": [
                    {
                        "chapter_number": 1.0,
                        "volume_number": 1,
                        "title": "Неоновый дождь",
                        "pages": 3,
                    },
                    {
                        "chapter_number": 2.0,
                        "volume_number": 1,
                        "title": "Взлом нейросети",
                        "pages": 3,
                    },
                ],
            }
        ],
    },
    {
        "title": "Кошачье Кафе и Магия",
        "slug": "cat-cafe-magic",
        "original_title": "Cat Cafe & Magic",
        "description": "Уютная история о девушке, унаследовавшей кафе, где котики умеют говорить и тайком помогают посетителям решать жизненные проблемы.",
        "cover_url": "https://placehold.co/400x600/fef3c7/d97706.png?text=Cat+Cafe",
        "banner_url": "https://placehold.co/1200x400/fef3c7/d97706.png?text=Cat+Cafe+Banner",
        "status": "ongoing",
        "type": "manga",
        "release_year": 2023,
        "rating": 9.5,
        "views_count": 18200,
        "genres": ["slice-of-life", "comedy", "supernatural"],
        "authors": [("Yumi Hoshino", "author")],
        "sources": [
            {
                "source_name": "local_seed",
                "source_manga_id": "local-catcafe-003",
                "source_url": "https://onigiri.punk.uz/manga/cat-cafe-magic",
                "chapters": [
                    {
                        "chapter_number": 1.0,
                        "volume_number": 1,
                        "title": "Лапки и эспрессо",
                        "pages": 4,
                    },
                    {
                        "chapter_number": 1.5,
                        "volume_number": 1,
                        "title": "Кошачий гороскоп",
                        "pages": 2,
                    },
                    {
                        "chapter_number": 2.0,
                        "volume_number": 1,
                        "title": "Заколдованный круассан",
                        "pages": 3,
                    },
                ],
            }
        ],
    },
    {
        "title": "Сага Звёздного Клинка",
        "slug": "stellar-blade-saga",
        "original_title": "Stellar Blade Saga",
        "description": "Древний звездный крейсер дрейфует на границе неизведанного космоса. Последний рыцарь пробуждается от векового криосна.",
        "cover_url": "https://placehold.co/400x600/1e1b4b/a855f7.png?text=Stellar+Blade",
        "banner_url": "https://placehold.co/1200x400/1e1b4b/a855f7.png?text=Stellar+Blade+Banner",
        "status": "completed",
        "type": "manhua",
        "release_year": 2022,
        "rating": 8.4,
        "views_count": 6100,
        "genres": ["space-opera", "fantasy"],
        "authors": [("Takeshi Vance", "author")],
        "sources": [
            {
                "source_name": "mangadex",
                "source_manga_id": "md-stellar-004",
                "source_url": "https://mangadex.org/title/dummy-stellar-004",
                "chapters": [
                    {
                        "chapter_number": 1.0,
                        "volume_number": 1,
                        "title": "Пробуждение флагмана",
                        "pages": 3,
                    }
                ],
            }
        ],
    },
]


def seed_data(conn: sqlite3.Connection) -> None:
    """
    Populate database with sample dummy catalog data.
    Idempotent: will insert or update existing records without creating duplicates.
    """
    cursor = conn.cursor()

    # 1. Insert Genres
    genre_id_by_slug = {}
    for name, slug in SAMPLE_GENRES:
        cursor.execute(
            """
            INSERT INTO genres (name, slug)
            VALUES (?, ?)
            ON CONFLICT(slug) DO UPDATE SET name = excluded.name
            RETURNING id, slug
            """,
            (name, slug),
        )
        row = cursor.fetchone()
        genre_id_by_slug[row["slug"]] = row["id"]

    # 2. Insert Authors
    author_id_by_name = {}
    for author_name in SAMPLE_AUTHORS:
        cursor.execute(
            """
            INSERT INTO authors (name)
            VALUES (?)
            ON CONFLICT(name) DO UPDATE SET name = excluded.name
            RETURNING id, name
            """,
            (author_name,),
        )
        row = cursor.fetchone()
        author_id_by_name[row["name"]] = row["id"]

    # 3. Insert Manga records
    for manga_data in SAMPLE_MANGA:
        slug = manga_data["slug"]
        cursor.execute(
            """
            INSERT INTO manga (
                title, slug, original_title, description, cover_url, banner_url,
                status, type, release_year, rating, views_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                title = excluded.title,
                original_title = excluded.original_title,
                description = excluded.description,
                cover_url = excluded.cover_url,
                banner_url = excluded.banner_url,
                status = excluded.status,
                type = excluded.type,
                release_year = excluded.release_year,
                rating = excluded.rating,
                views_count = excluded.views_count,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
            """,
            (
                manga_data["title"],
                slug,
                manga_data["original_title"],
                manga_data["description"],
                manga_data["cover_url"],
                manga_data["banner_url"],
                manga_data["status"],
                manga_data["type"],
                manga_data["release_year"],
                manga_data["rating"],
                manga_data["views_count"],
            ),
        )
        manga_id = cursor.fetchone()["id"]

        # 4. Link Manga to Genres
        for genre_slug in manga_data.get("genres", []):
            if genre_slug in genre_id_by_slug:
                g_id = genre_id_by_slug[genre_slug]
                cursor.execute(
                    """
                    INSERT INTO manga_genres (manga_id, genre_id)
                    VALUES (?, ?)
                    ON CONFLICT(manga_id, genre_id) DO NOTHING
                    """,
                    (manga_id, g_id),
                )

        # 5. Link Manga to Authors
        for author_name, role in manga_data.get("authors", []):
            if author_name in author_id_by_name:
                a_id = author_id_by_name[author_name]
                cursor.execute(
                    """
                    INSERT INTO manga_authors (manga_id, author_id, role)
                    VALUES (?, ?, ?)
                    ON CONFLICT(manga_id, author_id, role) DO NOTHING
                    """,
                    (manga_id, a_id, role),
                )

        # 6. Insert Manga Sources & Chapters
        for source_info in manga_data.get("sources", []):
            cursor.execute(
                """
                INSERT INTO manga_sources (manga_id, source_name, source_manga_id, source_url)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(manga_id, source_name, source_manga_id) DO UPDATE SET
                    source_url = excluded.source_url,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
                """,
                (
                    manga_id,
                    source_info["source_name"],
                    source_info["source_manga_id"],
                    source_info.get("source_url"),
                ),
            )
            manga_source_id = cursor.fetchone()["id"]

            # Insert chapters for this source
            for ch in source_info.get("chapters", []):
                cursor.execute(
                    """
                    INSERT INTO chapters (
                        manga_id, manga_source_id, chapter_number, volume_number, title
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(manga_source_id, chapter_number) DO UPDATE SET
                        manga_id = excluded.manga_id,
                        volume_number = excluded.volume_number,
                        title = excluded.title,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id
                    """,
                    (
                        manga_id,
                        manga_source_id,
                        ch["chapter_number"],
                        ch.get("volume_number"),
                        ch.get("title"),
                    ),
                )
                chapter_id = cursor.fetchone()["id"]

                # Insert dummy pages
                page_count = ch.get("pages", 1)
                for page_num in range(1, page_count + 1):
                    page_url = (
                        f"https://placehold.co/800x1200/png?text={slug}+Ch{ch['chapter_number']}+P{page_num}"
                    )
                    cursor.execute(
                        """
                        INSERT INTO chapter_pages (chapter_id, page_number, image_url)
                        VALUES (?, ?, ?)
                        ON CONFLICT(chapter_id, page_number) DO UPDATE SET
                            image_url = excluded.image_url
                        """,
                        (chapter_id, page_num, page_url),
                    )

    conn.commit()
    logger.info("Database successfully populated with seed data.")


def main() -> None:
    """CLI runner for seed service."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    init_db()
    conn = get_connection()
    try:
        seed_data(conn)
        print("[OK] Seed completed successfully.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
