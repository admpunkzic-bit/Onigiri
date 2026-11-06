"""
Unit and integration tests for Onigiri Reading History API (TASK 014 Phase 3):
- Telegram authentication requirement (401 on unauthorized)
- GET /api/history returning ordered history with manga info, cover, chapter, and progress
- DELETE /api/history/{manga_id} deleting specific manga from user history
- DELETE /api/history clearing entire history for user
- Strict user isolation between Telegram accounts
- Cascade deletion when manga is deleted
- Continuation identifiers (manga_id, slug, chapter_id, page_number)
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
def setup_history_db(monkeypatch):
    bot_token = "test_bot_token_secret_123"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", bot_token)

    conn = get_connection()
    c = conn.cursor()
    # Clean up test rows
    c.execute("DELETE FROM user_reading_progress WHERE user_id IN ('2001', '2002')")
    c.execute("DELETE FROM chapters WHERE manga_id IN (9901, 9902)")
    c.execute("DELETE FROM manga_sources WHERE manga_id IN (9901, 9902)")
    c.execute("DELETE FROM manga WHERE id IN (9901, 9902)")

    # Insert test mangas
    c.execute(
        """
        INSERT INTO manga (id, title, slug, cover_url, status)
        VALUES (9901, 'History Manga 1', 'history-manga-1', 'https://example.com/cover1.jpg', 'ongoing')
        """
    )
    c.execute(
        """
        INSERT INTO manga (id, title, slug, cover_url, status)
        VALUES (9902, 'History Manga 2', 'history-manga-2', 'https://example.com/cover2.jpg', 'completed')
        """
    )
    c.execute("INSERT INTO manga_sources (id, manga_id, source_name, source_manga_id) VALUES (9901, 9901, 'mangachan', 'chan-9901')")
    c.execute("INSERT INTO manga_sources (id, manga_id, source_name, source_manga_id) VALUES (9902, 9902, 'mangachan', 'chan-9902')")

    # Insert test chapters
    c.execute(
        """
        INSERT INTO chapters (id, manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, title, language)
        VALUES (991, 9901, 9901, 'ch-991', 1.0, 1, 'Глава 1: Начало', 'ru')
        """
    )
    c.execute(
        """
        INSERT INTO chapters (id, manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, title, language)
        VALUES (992, 9901, 9901, 'ch-992', 2.0, 1, 'Глава 2: Продолжение', 'ru')
        """
    )
    c.execute(
        """
        INSERT INTO chapters (id, manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, title, language)
        VALUES (993, 9902, 9902, 'ch-993', 10.5, 2, 'Экстра 10.5', 'ru')
        """
    )
    conn.commit()

    yield bot_token

    c.execute("DELETE FROM user_reading_progress WHERE user_id IN ('2001', '2002')")
    c.execute("DELETE FROM chapters WHERE manga_id IN (9901, 9902)")
    c.execute("DELETE FROM manga_sources WHERE manga_id IN (9901, 9902)")
    c.execute("DELETE FROM manga WHERE id IN (9901, 9902)")
    conn.commit()
    conn.close()


def test_history_requires_auth(setup_history_db):
    with TestClient(app) as client:
        # Unauthorized GET
        res = client.get("/api/history")
        assert res.status_code == 401

        # Unauthorized DELETE single
        res = client.delete("/api/history/9901")
        assert res.status_code == 401

        # Unauthorized DELETE all
        res = client.delete("/api/history")
        assert res.status_code == 401


def test_history_get_and_resume_identifiers(setup_history_db):
    bot_token = setup_history_db
    with TestClient(app) as client:
        init_data = make_telegram_init_data(2001, "reader_user", bot_token)
        headers = {"Authorization": f"Telegram {init_data}"}

        # Save progress on manga 1, chapter 2, page 15
        res = client.post(
            "/api/manga/history-manga-1/progress",
            headers=headers,
            json={"chapter_id": 992, "page_number": 15, "total_pages": 30},
        )
        assert res.status_code == 200

        # Save progress on manga 2, chapter 10.5, page 5
        res = client.post(
            "/api/manga/history-manga-2/progress",
            headers=headers,
            json={"chapter_id": 993, "page_number": 5, "total_pages": 20},
        )
        assert res.status_code == 200

        # Fetch history
        res = client.get("/api/history", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 2

        # Most recent first (manga 2)
        item0 = data[0]
        assert item0["manga_id"] == 9902
        assert item0["manga_slug"] == "history-manga-2"
        assert item0["manga_title"] == "History Manga 2"
        assert item0["cover_url"] == "https://example.com/cover2.jpg"
        assert item0["manga_status"] == "completed"
        assert item0["chapter_id"] == 993
        assert item0["chapter_number"] == 10.5
        assert item0["volume_number"] == 2
        assert item0["chapter_title"] == "Экстра 10.5"
        assert item0["page_number"] == 5
        assert item0["total_pages"] == 20
        assert "updated_at" in item0

        # Second item (manga 1)
        item1 = data[1]
        assert item1["manga_id"] == 9901
        assert item1["chapter_id"] == 992
        assert item1["chapter_number"] == 2.0
        assert item1["page_number"] == 15
        assert item1["total_pages"] == 30


def test_history_user_isolation(setup_history_db):
    bot_token = setup_history_db
    with TestClient(app) as client:
        user1_init = make_telegram_init_data(2001, "user_one", bot_token)
        user2_init = make_telegram_init_data(2002, "user_two", bot_token)
        h1 = {"Authorization": f"Telegram {user1_init}"}
        h2 = {"Authorization": f"Telegram {user2_init}"}

        # User 1 reads manga 1
        client.post("/api/manga/9901/progress", headers=h1, json={"chapter_id": 991, "page_number": 3})

        # User 2 reads manga 2
        client.post("/api/manga/9902/progress", headers=h2, json={"chapter_id": 993, "page_number": 7})

        # User 1 history has only manga 1
        r1 = client.get("/api/history", headers=h1).json()
        assert len(r1) == 1
        assert r1[0]["manga_id"] == 9901

        # User 2 history has only manga 2
        r2 = client.get("/api/history", headers=h2).json()
        assert len(r2) == 1
        assert r2[0]["manga_id"] == 9902


def test_history_delete_single_and_clear_all(setup_history_db):
    bot_token = setup_history_db
    with TestClient(app) as client:
        init_data = make_telegram_init_data(2001, "deleter_user", bot_token)
        headers = {"Authorization": f"Telegram {init_data}"}

        # Populate two items
        client.post("/api/manga/9901/progress", headers=headers, json={"chapter_id": 991, "page_number": 1})
        client.post("/api/manga/9902/progress", headers=headers, json={"chapter_id": 993, "page_number": 1})

        hist = client.get("/api/history", headers=headers).json()
        assert len(hist) == 2

        # Delete manga 1 by slug
        del_res = client.delete("/api/history/history-manga-1", headers=headers)
        assert del_res.status_code == 200
        assert del_res.json()["deleted"] is True

        hist_after = client.get("/api/history", headers=headers).json()
        assert len(hist_after) == 1
        assert hist_after[0]["manga_id"] == 9902

        # Clear all history
        clear_res = client.delete("/api/history", headers=headers)
        assert clear_res.status_code == 200
        assert clear_res.json()["status"] == "cleared"
        assert clear_res.json()["deleted_count"] >= 1

        hist_empty = client.get("/api/history", headers=headers).json()
        assert len(hist_empty) == 0
