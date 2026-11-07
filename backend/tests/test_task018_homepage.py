import sqlite3
import pytest
from fastapi.testclient import TestClient

from main import app
from schemas.manga import HomepageDataRead, HomepageCollectionRead
from services.catalog import CatalogService
from database.migrations import run_migrations


@pytest.fixture
def test_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)

    cursor = conn.cursor()

    # Seed manga with various statuses, genres, views, and ratings
    # 1. Completed Action/Fantasy with Russian source
    cursor.execute("""
        INSERT INTO manga (id, title, slug, status, type, rating, views_count, created_at, updated_at)
        VALUES (1, 'Solo Leveling', 'solo-leveling', 'completed', 'manhwa', 9.5, 500, '2026-01-01 10:00:00', '2026-01-10 10:00:00')
    """)
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (1, 'remanga', 'rem-1')")

    # 2. Completed Romance/Comedy with Russian source
    cursor.execute("""
        INSERT INTO manga (id, title, slug, status, type, rating, views_count, created_at, updated_at)
        VALUES (2, 'Horimiya', 'horimiya', 'completed', 'manga', 8.8, 200, '2026-01-02 10:00:00', '2026-01-12 10:00:00')
    """)
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (2, 'mangalib', 'lib-2')")

    # 3. Ongoing Action/Fantasy with Russian source
    cursor.execute("""
        INSERT INTO manga (id, title, slug, status, type, rating, views_count, created_at, updated_at)
        VALUES (3, 'Tower of God', 'tower-of-god', 'ongoing', 'manhwa', 9.2, 800, '2026-01-03 10:00:00', '2026-02-01 10:00:00')
    """)
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (3, 'remanga', 'rem-3')")

    # 4. Ongoing Romance/Comedy with Russian source
    cursor.execute("""
        INSERT INTO manga (id, title, slug, status, type, rating, views_count, created_at, updated_at)
        VALUES (4, 'Kaguya-sama', 'kaguya-sama', 'ongoing', 'manga', 9.0, 300, '2026-01-04 10:00:00', '2026-01-20 10:00:00')
    """)
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (4, 'mangalib', 'lib-4')")

    # 5. Completed Action/Demons with Russian chapters
    cursor.execute("""
        INSERT INTO manga (id, title, slug, status, type, rating, views_count, created_at, updated_at)
        VALUES (5, 'Demon Slayer', 'demon-slayer', 'completed', 'manga', 8.5, 450, '2026-01-05 10:00:00', '2026-01-25 10:00:00')
    """)
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (5, 'remanga', 'rem-5')")
    cursor.execute("""
        INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, language, created_at, updated_at)
        VALUES (5, 5, 'ds-ch1', 1.0, 'ru', '2026-03-01 12:00:00', '2026-03-01 12:00:00')
    """)

    # 6. Ongoing Action/Sci-Fi (Newest added)
    cursor.execute("""
        INSERT INTO manga (id, title, slug, status, type, rating, views_count, created_at, updated_at)
        VALUES (6, 'Cyberpunk Manga', 'cyberpunk-manga', 'ongoing', 'manga', 7.5, 50, '2026-03-05 15:00:00', '2026-03-05 15:00:00')
    """)
    cursor.execute("INSERT INTO manga_sources (manga_id, source_name, source_manga_id) VALUES (6, 'remanga', 'rem-6')")

    # Seed genres
    cursor.execute("INSERT INTO genres (id, name, slug) VALUES (1, 'Action', 'action')")
    cursor.execute("INSERT INTO genres (id, name, slug) VALUES (2, 'Fantasy', 'fantasy')")
    cursor.execute("INSERT INTO genres (id, name, slug) VALUES (3, 'Romance', 'romance')")
    cursor.execute("INSERT INTO genres (id, name, slug) VALUES (4, 'Comedy', 'comedy')")
    cursor.execute("INSERT INTO genres (id, name, slug) VALUES (5, 'Demons', 'demons')")

    # Link manga to genres
    # Solo Leveling: Action, Fantasy
    cursor.execute("INSERT INTO manga_genres (manga_id, genre_id) VALUES (1, 1), (1, 2)")
    # Horimiya: Romance, Comedy
    cursor.execute("INSERT INTO manga_genres (manga_id, genre_id) VALUES (2, 3), (2, 4)")
    # Tower of God: Action, Fantasy
    cursor.execute("INSERT INTO manga_genres (manga_id, genre_id) VALUES (3, 1), (3, 2)")
    # Kaguya-sama: Romance, Comedy
    cursor.execute("INSERT INTO manga_genres (manga_id, genre_id) VALUES (4, 3), (4, 4)")
    # Demon Slayer: Action, Demons
    cursor.execute("INSERT INTO manga_genres (manga_id, genre_id) VALUES (5, 1), (5, 5)")
    # Cyberpunk Manga: Action
    cursor.execute("INSERT INTO manga_genres (manga_id, genre_id) VALUES (6, 1)")

    conn.commit()
    yield conn
    conn.close()


def test_popular_completed_strictly_completed(test_db: sqlite3.Connection):
    service = CatalogService(conn=test_db)
    items = service.get_popular_completed(limit=10)

    assert len(items) > 0
    for item in items:
        assert item.status == "completed", f"Expected completed status, got {item.status} for {item.title}"

    # Verify sorting by popularity: Solo Leveling (views 500) > Demon Slayer (views 450) > Horimiya (views 200)
    titles = [it.title for it in items]
    assert titles[0] == "Solo Leveling"
    assert "Tower of God" not in titles
    assert "Kaguya-sama" not in titles


def test_popular_ongoing_strictly_ongoing(test_db: sqlite3.Connection):
    service = CatalogService(conn=test_db)
    items = service.get_popular_ongoing(limit=10)

    assert len(items) > 0
    for item in items:
        assert item.status == "ongoing", f"Expected ongoing status, got {item.status} for {item.title}"

    titles = [it.title for it in items]
    assert titles[0] == "Tower of God"  # 800 views
    assert "Solo Leveling" not in titles
    assert "Horimiya" not in titles


def test_recently_added_ordered_by_created_at(test_db: sqlite3.Connection):
    service = CatalogService(conn=test_db)
    items = service.get_recently_added(limit=10)

    assert len(items) > 0
    # Cyberpunk Manga was created on 2026-03-05 (latest)
    assert items[0].title == "Cyberpunk Manga"


def test_recently_updated_ordered_by_chapter_timestamp(test_db: sqlite3.Connection):
    service = CatalogService(conn=test_db)
    items = service.get_recently_updated(limit=10)

    assert len(items) > 0
    # Demon Slayer has a Russian chapter created on 2026-03-01 12:00:00
    # Titles with explicit chapters are prioritized
    assert items[0].title == "Demon Slayer"


def test_personalized_recommendations_new_user_fallback(test_db: sqlite3.Connection):
    service = CatalogService(conn=test_db)
    items, is_personalized = service.get_personalized_recommendations(user_id=None, guest_manga_ids=None, limit=5)

    assert is_personalized is False
    assert len(items) > 0
    # Fallback returns top popular items across catalog
    assert items[0].title == "Tower of God"


def test_personalized_recommendations_excludes_read_and_library_manga(test_db: sqlite3.Connection):
    service = CatalogService(conn=test_db)

    # User has Solo Leveling (ID 1) in library and Tower of God (ID 3) in reading progress
    # Both are Action + Fantasy!
    cursor = test_db.cursor()
    cursor.execute("INSERT INTO user_library (user_id, manga_id) VALUES ('user_123', 1)")
    cursor.execute("""
        INSERT INTO user_reading_progress (user_id, manga_id, chapter_id, translation_id, page_number)
        VALUES ('user_123', 3, 1, 'remanga:default', 1)
    """)
    test_db.commit()

    items, is_personalized = service.get_personalized_recommendations(user_id="user_123", limit=5)

    assert is_personalized is True
    assert len(items) > 0

    recommended_ids = [it.id for it in items]
    # Strictly must NOT contain 1 or 3
    assert 1 not in recommended_ids, "Solo Leveling should be excluded as it is in library"
    assert 3 not in recommended_ids, "Tower of God should be excluded as it is in reading progress"

    # Recommended manga should match Action/Fantasy preferences:
    # Demon Slayer (Action, Demons) and Cyberpunk (Action) should rank higher than Romance/Comedy Horimiya
    rec_titles = [it.title for it in items]
    assert "Demon Slayer" in rec_titles


def test_personalized_guest_manga_ids(test_db: sqlite3.Connection):
    service = CatalogService(conn=test_db)

    # Guest user has Horimiya (ID 2, Romance/Comedy) in local storage
    items, is_personalized = service.get_personalized_recommendations(guest_manga_ids=[2], limit=5)

    assert is_personalized is True
    recommended_ids = [it.id for it in items]
    assert 2 not in recommended_ids, "Horimiya should be excluded as it was in guest list"

    # Should recommend Kaguya-sama (Romance/Comedy) as top recommendation!
    assert items[0].title == "Kaguya-sama"


def test_homepage_api_endpoint():
    with TestClient(app) as client:
        resp = client.get("/api/homepage")
        assert resp.status_code == 200
        data = resp.json()

        assert "popular_completed" in data
        assert "popular_ongoing" in data
        assert "for_you" in data
        assert "recently_added" in data
        assert "recently_updated" in data
        assert "continue_reading" in data

        # Check collection structure
        pop_comp = data["popular_completed"]
        assert pop_comp["title"] == "Популярное завершённое"
        assert pop_comp["see_all_url"] == "/search?status=completed&sort_by=popularity"
        assert isinstance(pop_comp["items"], list)

        # Check that completed collection only has completed manga
        for it in pop_comp["items"]:
            assert it["status"] == "completed"

        # Check that ongoing collection only has ongoing manga
        for it in data["popular_ongoing"]["items"]:
            assert it["status"] == "ongoing"


def test_individual_collections_api_endpoint():
    with TestClient(app) as client:
        # Test popular-completed
        r1 = client.get("/api/manga/collections/popular-completed")
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1["id"] == "popular_completed"
        for it in d1["items"]:
            assert it["status"] == "completed"

        # Test popular-ongoing
        r2 = client.get("/api/manga/collections/popular-ongoing")
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["id"] == "popular_ongoing"
        for it in d2["items"]:
            assert it["status"] == "ongoing"

        # Test for-you with guest IDs
        r3 = client.get("/api/manga/collections/for-you?guest_manga_ids=1051,1354")
        assert r3.status_code == 200
        d3 = r3.json()
        assert d3["id"] == "for_you"
        ids = [it["id"] for it in d3["items"]]
        assert 1051 not in ids
        assert 1354 not in ids

        # Test 404 for unknown collection
        r4 = client.get("/api/manga/collections/non-existent-collection")
        assert r4.status_code == 404

