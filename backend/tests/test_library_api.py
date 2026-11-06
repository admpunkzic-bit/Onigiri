"""
Unit and integration tests for Onigiri Personal Manga Library API (TASK 013 Phase 1):
- Cryptographic Telegram initData authentication
- Adding, retrieving, and removing manga in library
- Lightweight /library/ids endpoint for star badges
- User isolation between different Telegram accounts
- Independence from chapters existence (starring titles without chapters)
- Cascade deletion when manga is deleted
"""

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from database.connection import get_connection
from main import app


def make_telegram_init_data(user_id: int, username: str, bot_token: str, age_seconds: int = 0) -> str:
    auth_date = int(time.time()) - age_seconds
    user_json = json.dumps({"id": user_id, "username": username, "first_name": "Test"})
    params = [
        ("auth_date", str(auth_date)),
        ("query_id", "AAG_test_query"),
        ("user", user_json),
    ]
    sorted_params = sorted(params, key=lambda x: x[0])
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_params)

    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    hash_val = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    return f"auth_date={auth_date}&query_id=AAG_test_query&user={user_json}&hash={hash_val}"


@pytest.fixture
def test_db_for_library():
    conn = get_connection()
    c = conn.cursor()
    # Clean up test records
    c.execute("DELETE FROM user_library WHERE user_id IN ('1001', '1002')")
    c.execute("DELETE FROM chapters WHERE manga_id IN (980, 981)")
    c.execute("DELETE FROM manga_sources WHERE manga_id IN (980, 981)")
    c.execute("DELETE FROM manga WHERE id IN (980, 981)")
    conn.commit()

    # Insert two test manga: one with chapters, one without
    c.execute(
        """
        INSERT OR IGNORE INTO manga (id, title, slug, status, type, rating, views_count)
        VALUES
        (980, 'Library Manga One', 'library-manga-one', 'ongoing', 'manga', 8.5, 50),
        (981, 'Library Manga Zero Chapters', 'library-manga-zero', 'completed', 'manhwa', 9.0, 10)
        """
    )
    c.execute(
        """
        INSERT OR IGNORE INTO manga_sources (id, manga_id, source_name, source_manga_id)
        VALUES
        (980, 980, 'mangadex', 'md-lib-1'),
        (981, 981, 'mangadex', 'md-lib-2')
        """
    )
    c.execute(
        """
        INSERT OR IGNORE INTO chapters (id, manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, title, language)
        VALUES
        (9801, 980, 980, 'md-ch-9801', 1.0, 1, 'First Chapter', 'ru')
        """
    )
    conn.commit()
    yield conn

    # Teardown
    c.execute("DELETE FROM user_library WHERE user_id IN ('1001', '1002')")
    c.execute("DELETE FROM chapters WHERE manga_id IN (980, 981)")
    c.execute("DELETE FROM manga_sources WHERE manga_id IN (980, 981)")
    c.execute("DELETE FROM manga WHERE id IN (980, 981)")
    conn.commit()


def test_library_requires_auth():
    with TestClient(app) as client:
        # GET /api/library without auth header
        res = client.get("/api/library")
        assert res.status_code == 401

        # GET /api/library/ids without auth header
        res_ids = client.get("/api/library/ids")
        assert res_ids.status_code == 401

        # POST /api/library/1 without auth header
        res_add = client.post("/api/library/1")
        assert res_add.status_code == 401


def test_library_add_and_retrieve(test_db_for_library, monkeypatch):
    bot_token = "test_bot_token_lib"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", bot_token)
    user_init = make_telegram_init_data(user_id=1001, username="star_reader", bot_token=bot_token)
    headers = {"Authorization": f"Telegram {user_init}"}

    with TestClient(app) as client:
        # 1. Initial state: empty library
        res_ids = client.get("/api/library/ids", headers=headers)
        assert res_ids.status_code == 200
        assert res_ids.json() == []

        # 2. Add manga 980 by slug
        add_res = client.post("/api/library/library-manga-one", headers=headers)
        assert add_res.status_code == 200
        data = add_res.json()
        assert data["status"] == "added"
        assert data["manga_id"] == 980
        assert data["manga"]["title"] == "Library Manga One"

        # 3. Verify lightweight IDs endpoint
        res_ids2 = client.get("/api/library/ids", headers=headers)
        assert res_ids2.status_code == 200
        assert res_ids2.json() == [980]

        # 4. Verify full library list
        res_list = client.get("/api/library", headers=headers)
        assert res_list.status_code == 200
        items = res_list.json()
        assert len(items) == 1
        assert items[0]["id"] == 980
        assert items[0]["title"] == "Library Manga One"


def test_library_independent_from_chapters(test_db_for_library, monkeypatch):
    """Manga with 0 chapters must be addable to library and retrievable."""
    bot_token = "test_bot_token_lib"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", bot_token)
    user_init = make_telegram_init_data(user_id=1001, username="star_reader", bot_token=bot_token)
    headers = {"Authorization": f"Telegram {user_init}"}

    with TestClient(app) as client:
        # Manga 981 has 0 chapters
        add_res = client.post("/api/library/981", headers=headers)
        assert add_res.status_code == 200
        assert add_res.json()["manga_id"] == 981

        res_list = client.get("/api/library", headers=headers)
        assert res_list.status_code == 200
        ids = [m["id"] for m in res_list.json()]
        assert 981 in ids


def test_library_remove(test_db_for_library, monkeypatch):
    bot_token = "test_bot_token_lib"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", bot_token)
    user_init = make_telegram_init_data(user_id=1001, username="star_reader", bot_token=bot_token)
    headers = {"Authorization": f"Telegram {user_init}"}

    with TestClient(app) as client:
        # Add manga 980
        client.post("/api/library/980", headers=headers)
        assert 980 in client.get("/api/library/ids", headers=headers).json()

        # Remove manga 980
        del_res = client.delete("/api/library/library-manga-one", headers=headers)
        assert del_res.status_code == 200
        assert del_res.json()["removed"] is True

        # Verify no longer in library
        assert 980 not in client.get("/api/library/ids", headers=headers).json()

        # Idempotent delete returns removed: False
        del_again = client.delete("/api/library/980", headers=headers)
        assert del_again.status_code == 200
        assert del_again.json()["removed"] is False


def test_library_user_isolation(test_db_for_library, monkeypatch):
    """User 1001 and User 1002 must have completely independent libraries."""
    bot_token = "test_bot_token_lib"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", bot_token)
    user1_init = make_telegram_init_data(user_id=1001, username="user_one", bot_token=bot_token)
    user2_init = make_telegram_init_data(user_id=1002, username="user_two", bot_token=bot_token)

    h1 = {"Authorization": f"Telegram {user1_init}"}
    h2 = {"Authorization": f"Telegram {user2_init}"}

    with TestClient(app) as client:
        # User 1 adds 980
        client.post("/api/library/980", headers=h1)

        # User 2 adds 981
        client.post("/api/library/981", headers=h2)

        # Check User 1 library
        u1_ids = client.get("/api/library/ids", headers=h1).json()
        assert u1_ids == [980]

        # Check User 2 library
        u2_ids = client.get("/api/library/ids", headers=h2).json()
        assert u2_ids == [981]

        # User 1 removing 980 does not affect User 2
        client.delete("/api/library/980", headers=h1)
        assert client.get("/api/library/ids", headers=h1).json() == []
        assert client.get("/api/library/ids", headers=h2).json() == [981]


def test_library_cascade_deletion(test_db_for_library, monkeypatch):
    """Deleting a manga from catalog cascades to user_library."""
    bot_token = "test_bot_token_lib"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", bot_token)
    user_init = make_telegram_init_data(user_id=1001, username="cascade_user", bot_token=bot_token)
    headers = {"Authorization": f"Telegram {user_init}"}

    with TestClient(app) as client:
        client.post("/api/library/980", headers=headers)
        assert 980 in client.get("/api/library/ids", headers=headers).json()

        # Delete manga 980 from manga table
        cursor = test_db_for_library.cursor()
        cursor.execute("DELETE FROM manga WHERE id = 980")
        test_db_for_library.commit()

        # Must no longer be in library
        assert 980 not in client.get("/api/library/ids", headers=headers).json()
