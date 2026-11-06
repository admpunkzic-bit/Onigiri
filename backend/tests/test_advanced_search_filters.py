"""
Tests for Advanced Search Filters and Genre Discovery (TASK 014).
Validates /api/manga/genres, optional 'q' search, multi-criteria filtering,
author and genre matching, and sorting.
"""

import pytest
from fastapi.testclient import TestClient
from main import app
from database.connection import get_connection
from database.migrations import run_migrations


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    conn = get_connection()
    run_migrations(conn)


def test_get_all_genres_endpoint(client: TestClient):
    """GET /api/manga/genres returns active genres list with slug and name."""
    response = client.get("/api/manga/genres")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0

    first = data[0]
    assert "id" in first
    assert "name" in first
    assert "slug" in first


def test_search_manga_without_q_param(client: TestClient):
    """GET /api/manga/search without 'q' query returns catalog items sorted by popularity."""
    response = client.get("/api/manga/search?limit=10")
    assert response.status_code == 200
    items = response.json()
    assert isinstance(items, list)
    assert len(items) > 0


def test_search_filter_by_genre(client: TestClient):
    """GET /api/manga/search?genre=action returns titles containing Action genre."""
    response = client.get("/api/manga/search?genre=action&limit=10")
    assert response.status_code == 200
    items = response.json()
    assert isinstance(items, list)
    assert len(items) > 0

    # Every returned item should have 'Action' or matching slug in its genres
    for item in items:
        genre_slugs = {g["slug"].lower() for g in item.get("genres", [])}
        assert "action" in genre_slugs


def test_search_filter_by_author(client: TestClient):
    """GET /api/manga/search?author=Miura returns Berserk."""
    response = client.get("/api/manga/search?author=Miura&limit=10")
    assert response.status_code == 200
    items = response.json()
    assert isinstance(items, list)
    assert len(items) > 0

    titles = [m["title"].lower() for m in items]
    assert any("berserk" in t for t in titles)


def test_search_filter_by_status_and_type(client: TestClient):
    """GET /api/manga/search with type and status filtering."""
    response = client.get("/api/manga/search?type=manga&status=ongoing&limit=5")
    assert response.status_code == 200
    items = response.json()
    assert isinstance(items, list)

    for item in items:
        if item.get("status"):
            assert item["status"].lower() == "ongoing"
        if item.get("type"):
            assert item["type"].lower() == "manga"


def test_search_filter_by_excluded_genre(client: TestClient):
    """GET /api/manga/search with excluded_genre excludes titles with that genre."""
    response = client.get("/api/manga/search?genre=action&excluded_genre=romance&limit=10")
    assert response.status_code == 200
    items = response.json()
    assert isinstance(items, list)

    for item in items:
        genre_slugs = {g["slug"].lower() for g in item.get("genres", [])}
        assert "romance" not in genre_slugs


def test_search_sorting_by_rating(client: TestClient):
    """GET /api/manga/search?sort_by=rating&sort_order=desc returns sorted items."""
    response = client.get("/api/manga/search?sort_by=rating&sort_order=desc&limit=10")
    assert response.status_code == 200
    items = response.json()
    assert len(items) > 0

    ratings = [item["rating"] for item in items if item["rating"] is not None]
    # Check non-ascending order
    for i in range(len(ratings) - 1):
        assert ratings[i] >= ratings[i + 1] - 0.0001
