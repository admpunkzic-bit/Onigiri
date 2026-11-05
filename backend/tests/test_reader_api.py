"""
Unit and integration tests for Onigiri Manga Reader API:
- Telegram initData cryptographic verification (HMAC-SHA256)
- SSRF protection (loopback, private, cloud metadata, domain allowlist, no redirects)
- Chapter reader detail and adjacent navigation
- Reading progress persistence and user isolation
"""

import hashlib
import hmac
import json
import socket
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.auth import verify_telegram_init_data
from database.connection import get_connection
from main import app
from providers.base import (
    BaseMangaProvider,
    ProviderPageItem,
    ProviderPagesResult,
)
from providers.registry import ProviderRegistry
from services.reader import ReaderService, validate_and_resolve_url_ssrf


# ==============================================================================
# Helper to generate cryptographically valid Telegram initData
# ==============================================================================

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


# ==============================================================================
# 1. Telegram Auth Tests
# ==============================================================================

def test_telegram_auth_valid():
    bot_token = "123456789:ABCdefGhIJKlmNoPQRstuVWXyz"
    init_data = make_telegram_init_data(user_id=777, username="onigiri_reader", bot_token=bot_token)

    verified = verify_telegram_init_data(init_data, bot_token=bot_token)
    assert verified is not None
    assert verified["id"] == 777
    assert verified["username"] == "onigiri_reader"


def test_telegram_auth_tampered_hash_rejected():
    bot_token = "123456789:ABCdefGhIJKlmNoPQRstuVWXyz"
    init_data = make_telegram_init_data(user_id=777, username="onigiri_reader", bot_token=bot_token)
    tampered_data = init_data.replace("hash=", "hash=deadbeef001122")

    verified = verify_telegram_init_data(tampered_data, bot_token=bot_token)
    assert verified is None


def test_telegram_auth_expired_auth_date_rejected():
    bot_token = "123456789:ABCdefGhIJKlmNoPQRstuVWXyz"
    # 25 hours old (> 86400s)
    expired_init_data = make_telegram_init_data(
        user_id=777, username="onigiri_reader", bot_token=bot_token, age_seconds=90000
    )

    verified = verify_telegram_init_data(expired_init_data, bot_token=bot_token)
    assert verified is None


def test_telegram_auth_missing_token():
    init_data = "auth_date=1000&hash=abc"
    assert verify_telegram_init_data(init_data, bot_token=None) is None


# ==============================================================================
# 2. SSRF Protection Tests
# ==============================================================================

def test_ssrf_rejects_non_https():
    with pytest.raises(HTTPException) as exc_info:
        validate_and_resolve_url_ssrf("http://cmdxd.mangadex.network/data/1.png")
    assert exc_info.value.status_code == 400
    assert "Only HTTPS" in exc_info.value.detail


def test_ssrf_rejects_unauthorized_domain():
    with pytest.raises(HTTPException) as exc_info:
        validate_and_resolve_url_ssrf("https://evil-attacker.com/data/1.png")
    assert exc_info.value.status_code == 403
    assert "SSRF protection" in exc_info.value.detail


def test_ssrf_rejects_credentials_in_url():
    with pytest.raises(HTTPException) as exc_info:
        validate_and_resolve_url_ssrf("https://admin:pass@cmdxd.mangadex.network/data/1.png")
    assert exc_info.value.status_code == 400
    assert "credentials" in exc_info.value.detail


def test_ssrf_rejects_loopback_and_private_ips():
    # Simulate DNS resolving mangadex.network to 127.0.0.1
    with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]):
        with pytest.raises(HTTPException) as exc_info:
            validate_and_resolve_url_ssrf("https://node.mangadex.network/data/1.png")
        assert exc_info.value.status_code == 403
        assert "restricted IP" in exc_info.value.detail

    # Simulate DNS resolving to AWS/GCP cloud metadata IP 169.254.169.254
    with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443))]):
        with pytest.raises(HTTPException) as exc_info:
            validate_and_resolve_url_ssrf("https://node.mangadex.network/data/1.png")
        assert exc_info.value.status_code == 403
        assert "restricted IP" in exc_info.value.detail


def test_ssrf_accepts_valid_public_mangadex_network():
    # Public non-reserved IP e.g. 93.184.216.34
    with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]):
        # Should not raise exception
        validate_and_resolve_url_ssrf("https://cmdxd98sb0x3yprd.mangadex.network:44300/data/hash/1.png")


# ==============================================================================
# 3. Chapter Pages & Reading Progress Integration Tests
# ==============================================================================

class DummyReaderProvider(BaseMangaProvider):
    @property
    def provider_id(self) -> str:
        return "mangadex"

    @property
    def name(self) -> str:
        return "MangaDex"

    async def search(self, *args, **kwargs):
        raise NotImplementedError

    async def get_manga_details(self, *args, **kwargs):
        raise NotImplementedError

    async def get_chapters(self, *args, **kwargs):
        raise NotImplementedError

    async def get_chapter_pages(self, provider_chapter_id: str, data_saver: bool = False) -> ProviderPagesResult:
        return ProviderPagesResult(
            provider_id="mangadex",
            provider_chapter_id=provider_chapter_id,
            pages=[
                ProviderPageItem(page_number=1, image_url="https://cmdxd.mangadex.network/data/hash/1.png"),
                ProviderPageItem(page_number=2, image_url="https://cmdxd.mangadex.network/data/hash/2.png"),
                ProviderPageItem(page_number=3, image_url="https://cmdxd.mangadex.network/data/hash/3.png"),
            ],
            total_pages=3,
            data_saver=data_saver,
        )

    async def close(self):
        pass


@pytest.fixture
def test_db_with_chapters():
    conn = get_connection()
    c = conn.cursor()
    # Clean up any leftover test data
    c.execute("DELETE FROM user_reading_progress WHERE manga_id = 999")
    c.execute("DELETE FROM chapters WHERE manga_id = 999")
    c.execute("DELETE FROM manga_sources WHERE manga_id = 999")
    c.execute("DELETE FROM manga WHERE id = 999")
    conn.commit()

    # Insert test manga
    c.execute(
        """
        INSERT OR IGNORE INTO manga (id, title, slug, status, type, rating, views_count)
        VALUES (999, 'Reader Test Manga', 'reader-test-manga', 'ongoing', 'manga', 9.5, 100)
        """
    )
    c.execute(
        """
        INSERT OR IGNORE INTO manga_sources (id, manga_id, source_name, source_manga_id)
        VALUES (999, 999, 'mangadex', 'md-reader-test')
        """
    )
    # Insert two chapters (1.0 and 2.0)
    c.execute(
        """
        INSERT OR IGNORE INTO chapters (
            id, manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, title, language
        )
        VALUES
        (901, 999, 999, 'md-ch-901', 1.0, 1, 'First Chapter', 'ru'),
        (902, 999, 999, 'md-ch-902', 2.0, 1, 'Second Chapter', 'ru')
        """
    )
    conn.commit()
    yield conn


def test_reader_pages_and_navigation(test_db_with_chapters):
    mock_provider = DummyReaderProvider()
    registry = ProviderRegistry()
    registry.register(mock_provider)

    with TestClient(app) as client:
        app.state.provider_registry = registry

        # 1. Fetch reader detail for chapter 901
        res = client.get("/api/manga/reader-test-manga/chapters/901/pages")
        assert res.status_code == 200
        data = res.json()
        assert data["chapter_id"] == 901
        assert data["manga_title"] == "Reader Test Manga"
        assert data["total_pages"] == 3
        assert len(data["pages"]) == 3
        assert data["pages"][0]["page_number"] == 1
        assert data["pages"][0]["image_url"] == "/api/manga/chapters/901/pages/1"

        # Adjacent navigation
        assert data["prev_chapter_id"] is None
        assert data["next_chapter_id"] == 902

        # 2. Fetch reader detail for chapter 902
        res2 = client.get("/api/manga/reader-test-manga/chapters/902/pages")
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["prev_chapter_id"] == 901
        assert data2["next_chapter_id"] is None


def test_reading_progress_requires_telegram_auth(test_db_with_chapters):
    with TestClient(app) as client:
        # Without auth header -> 401
        r_unauth = client.get("/api/manga/reader-test-manga/progress")
        assert r_unauth.status_code == 401

        r_post_unauth = client.post(
            "/api/manga/reader-test-manga/progress",
            json={"chapter_id": 901, "page_number": 2, "total_pages": 3},
        )
        assert r_post_unauth.status_code == 401


def test_reading_progress_save_and_retrieve_with_telegram_auth(test_db_with_chapters, monkeypatch):
    bot_token = "test_bot_token_123"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", bot_token)

    user1_init = make_telegram_init_data(user_id=111, username="user_one", bot_token=bot_token)
    user2_init = make_telegram_init_data(user_id=222, username="user_two", bot_token=bot_token)

    mock_provider = DummyReaderProvider()
    registry = ProviderRegistry()
    registry.register(mock_provider)

    with TestClient(app) as client:
        app.state.provider_registry = registry

        # 1. User 1 initially has no progress
        r_init = client.get(
            "/api/manga/reader-test-manga/progress",
            headers={"Authorization": f"Telegram {user1_init}"},
        )
        assert r_init.status_code == 200
        assert r_init.json() is None

        # 2. User 1 saves progress on chapter 901, page 2
        r_save = client.post(
            "/api/manga/reader-test-manga/progress",
            headers={"Authorization": f"Telegram {user1_init}"},
            json={"chapter_id": 901, "page_number": 2, "total_pages": 3},
        )
        assert r_save.status_code == 200
        saved_data = r_save.json()
        assert saved_data["chapter_id"] == 901
        assert saved_data["page_number"] == 2
        assert saved_data["total_pages"] == 3

        # 3. User 1 retrieves progress
        r_get = client.get(
            "/api/manga/reader-test-manga/progress",
            headers={"Authorization": f"Telegram {user1_init}"},
        )
        assert r_get.status_code == 200
        assert r_get.json()["page_number"] == 2

        # 4. User 2 has isolated progress (still None)
        r_user2 = client.get(
            "/api/manga/reader-test-manga/progress",
            headers={"Authorization": f"Telegram {user2_init}"},
        )
        assert r_user2.status_code == 200
        assert r_user2.json() is None

        # 5. User 1 updates to chapter 902 page 1 (idempotent upsert)
        r_update = client.post(
            "/api/manga/reader-test-manga/progress",
            headers={"Authorization": f"Telegram {user1_init}"},
            json={"chapter_id": 902, "page_number": 1, "total_pages": 3},
        )
        assert r_update.status_code == 200
        assert r_update.json()["chapter_id"] == 902
        assert r_update.json()["page_number"] == 1
        assert r_update.json()["chapter_number"] == 2.0


def test_reading_progress_fractional_chapter(test_db_with_chapters, monkeypatch):
    bot_token = "test_bot_token_fractional"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", bot_token)
    user_init = make_telegram_init_data(user_id=888, username="fractional_reader", bot_token=bot_token)

    # Insert a fractional chapter 0.5
    cursor = test_db_with_chapters.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO chapters (
            id, manga_id, manga_source_id, source_chapter_id, chapter_number, volume_number, title, language
        )
        VALUES (903, 999, 999, 'md-ch-903', 0.5, 1, 'Prologue Part 2', 'ru')
        """
    )
    test_db_with_chapters.commit()

    with TestClient(app) as client:
        # Save progress on chapter 903 (0.5)
        res = client.post(
            "/api/manga/reader-test-manga/progress",
            headers={"Authorization": f"Telegram {user_init}"},
            json={"chapter_id": 903, "page_number": 5, "total_pages": 15},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["chapter_id"] == 903
        assert data["chapter_number"] == 0.5
        assert data["chapter_title"] == "Prologue Part 2"
        assert data["page_number"] == 5

        # Retrieve and verify preserved fractional number
        get_res = client.get(
            "/api/manga/reader-test-manga/progress",
            headers={"Authorization": f"Telegram {user_init}"},
        )
        assert get_res.status_code == 200
        get_data = get_res.json()
        assert get_data["chapter_number"] == 0.5
        assert get_data["chapter_id"] == 903


def test_schemas_support_unnumbered_chapter():
    from schemas.manga import ReadingProgressRead, ChapterReaderDetailRead

    # ReadingProgressRead with None chapter_number must not raise validation error
    prog = ReadingProgressRead(
        manga_id=999,
        chapter_id=904,
        chapter_number=None,
        chapter_title="Special One-shot",
        page_number=1,
        total_pages=10,
        updated_at="2026-11-06T00:00:00Z",
    )
    assert prog.chapter_number is None
    assert prog.chapter_title == "Special One-shot"

    # ChapterReaderDetailRead with None chapter_number must not raise validation error
    detail = ChapterReaderDetailRead(
        chapter_id=904,
        manga_id=999,
        manga_title="Test Manga",
        chapter_number=None,
        title="Special One-shot",
        total_pages=1,
        pages=[],
    )
    assert detail.chapter_number is None
    assert detail.title == "Special One-shot"
