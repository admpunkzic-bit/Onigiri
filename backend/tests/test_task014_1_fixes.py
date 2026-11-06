"""
Test suite for TASK 014.1 critical bug fixes:
1. Reader page loading: SSRF validation, redirects, multi-source fallback queue, AVIF/WebP sniffing.
2. Genre search: case-insensitive slug and name matching, strict filtering with text queries.
3. History covers: cover proxy hostname allowlist, HTTP-to-HTTPS upgrade, history cover backfill.
"""

import pytest
import sqlite3
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException
from fastapi.testclient import TestClient

from database.migrations import run_migrations
from services.reader import ReaderService, validate_and_resolve_url_ssrf
from services.catalog import CatalogService
from providers.base import ProviderMangaItem, ProviderPagesResult, ProviderPageItem
from providers.registry import ProviderRegistry
from main import app


@pytest.fixture
def test_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    yield conn
    conn.close()


# ==============================================================================
# 1. Reader Page Loading & Stream Tests
# ==============================================================================

def test_ssrf_validation_allowed_hosts():
    # MangaDex and Manga-Chan valid domains should not raise
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
        res1 = validate_and_resolve_url_ssrf("https://uploads.mangadex.org/covers/1/cover.jpg")
        assert res1.startswith("https://uploads.mangadex.org")

        res2 = validate_and_resolve_url_ssrf("https://imgcover.manga-chan.me/1.jpg")
        assert res2.startswith("https://imgcover.manga-chan.me")

        res3 = validate_and_resolve_url_ssrf("https://avifbig.manga-chan.me/online/1/2.avif")
        assert res3.startswith("https://avifbig.manga-chan.me")


def test_ssrf_rejects_unauthorized_host():
    with pytest.raises(HTTPException) as exc:
        validate_and_resolve_url_ssrf("https://malicious-site.com/image.jpg")
    assert exc.value.status_code == 403


def test_ssrf_rejects_non_https_scheme():
    with pytest.raises(HTTPException) as exc:
        validate_and_resolve_url_ssrf("http://uploads.mangadex.org/cover.jpg")
    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_reader_image_stream_follows_redirects(test_db):
    service = ReaderService(conn=test_db)

    # Insert test manga, source and chapter
    cursor = test_db.cursor()
    cursor.execute(
        "INSERT INTO manga (title, slug) VALUES ('Test Manga', 'test-manga')"
    )
    m_id = cursor.lastrowid
    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id, source_url) VALUES (?, 'mangachan', 'ch-1', 'url')",
        (m_id,),
    )
    s_id = cursor.lastrowid
    cursor.execute(
        """
        INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, language)
        VALUES (?, ?, 'src-ch-1', 1.0, 'ru')
        """,
        (m_id, s_id),
    )
    ch_id = cursor.lastrowid
    test_db.commit()

    # Mock get_athome_pages
    pages_mock = ProviderPagesResult(
        provider_id="mangachan",
        provider_chapter_id="src-ch-1",
        pages=[ProviderPageItem(page_number=1, image_url="https://img1.manga-chan.me/page1.jpg")]
    )

    # Mock httpx responses: first 301 redirect to avif, second 200 with AVIF bytes
    avif_bytes = b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1miaf" + b"x" * 20
    resp_redirect = MagicMock()
    resp_redirect.status_code = 301
    resp_redirect.headers = {"location": "https://avifbig.manga-chan.me/page1.avif"}

    resp_final = MagicMock()
    resp_final.status_code = 200
    resp_final.headers = {"content-type": "application/octet-stream"}
    resp_final.content = avif_bytes

    with patch.object(service, "get_athome_pages", AsyncMock(return_value=pages_mock)), \
         patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]), \
         patch("httpx.AsyncClient.get", AsyncMock(side_effect=[resp_redirect, resp_final])):

        raw, ctype = await service.get_page_image_stream(chapter_id=ch_id, page_number=1)
        assert raw == avif_bytes
        assert ctype == "image/avif"


# ==============================================================================
# 2. Genre Search & Case-Insensitive Filter Tests
# ==============================================================================

@pytest.mark.anyio
async def test_genre_search_case_insensitive(test_db):
    service = CatalogService(conn=test_db)
    cursor = test_db.cursor()

    # Insert test genres
    cursor.execute("INSERT INTO genres (name, slug) VALUES ('Экшен', 'action')")
    g_action = cursor.lastrowid
    cursor.execute("INSERT INTO genres (name, slug) VALUES ('Драма', 'drama')")
    g_drama = cursor.lastrowid

    # Insert test manga
    cursor.execute("INSERT INTO manga (title, slug, rating, views_count) VALUES ('Action Hero', 'action-hero', 8.5, 100)")
    m1 = cursor.lastrowid
    cursor.execute("INSERT INTO manga (title, slug, rating, views_count) VALUES ('Pure Drama', 'pure-drama', 7.0, 50)")
    m2 = cursor.lastrowid

    cursor.execute("INSERT INTO manga_genres (manga_id, genre_id) VALUES (?, ?)", (m1, g_action))
    cursor.execute("INSERT INTO manga_genres (manga_id, genre_id) VALUES (?, ?)", (m2, g_drama))
    test_db.commit()

    # 1. Search with lowercase slug 'action'
    res1 = await service.search(genres=["action"])
    assert len(res1) == 1
    assert res1[0].id == m1

    # 2. Search with uppercase slug 'ACTION'
    res2 = await service.search(genres=["ACTION"])
    assert len(res2) == 1
    assert res2[0].id == m1

    # 3. Search with Russian name 'Экшен'
    res3 = await service.search(genres=["Экшен"])
    assert len(res3) == 1
    assert res3[0].id == m1

    # 4. Search with lowercase Russian name 'экшен'
    res4 = await service.search(genres=["экшен"])
    assert len(res4) == 1
    assert res4[0].id == m1


# ==============================================================================
# 3. History Covers & Cover Proxy Tests
# ==============================================================================

def test_cover_proxy_rejects_unauthorized_host():
    client = TestClient(app)
    resp = client.get("/api/manga/cover/proxy", params={"url": "https://evil.com/cover.jpg"})
    assert resp.status_code == 400


def test_cover_proxy_accepts_and_proxies_allowed_host():
    client = TestClient(app)
    fake_img = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"fake-jpg-content"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "image/jpeg"}
    mock_resp.content = fake_img

    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]), \
         patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_resp)):

        # Tests HTTP auto-upgrade to HTTPS for authorized domain
        resp = client.get(
            "/api/manga/cover/proxy",
            params={"url": "http://imgcover.manga-chan.me/123/cover.jpg"},
        )
        assert resp.status_code == 200
        assert resp.content == fake_img
        assert resp.headers["content-type"] == "image/jpeg"


def test_history_cover_fallback_when_manga_cover_is_null(test_db):
    service = ReaderService(conn=test_db)
    cursor = test_db.cursor()

    # Create manga 1 without cover, and manga 2 with cover (same title)
    cursor.execute(
        "INSERT INTO manga (title, slug, cover_url) VALUES ('Berserk', 'berserk-chan', NULL)"
    )
    m1 = cursor.lastrowid
    cursor.execute(
        "INSERT INTO manga (title, slug, cover_url) VALUES ('Berserk', 'berserk-dex', 'https://uploads.mangadex.org/cover.jpg')"
    )

    cursor.execute(
        "INSERT INTO manga_sources (manga_id, source_name, source_manga_id, source_url) VALUES (?, 'mangachan', 'src-1', 'url')",
        (m1,),
    )
    s1 = cursor.lastrowid

    cursor.execute(
        "INSERT INTO chapters (manga_id, manga_source_id, source_chapter_id, chapter_number, language) VALUES (?, ?, 'ch1', 1.0, 'ru')",
        (m1, s1),
    )
    ch1 = cursor.lastrowid

    # Record reading progress for m1 (which has null cover)
    cursor.execute(
        """
        INSERT INTO user_reading_progress (user_id, manga_id, chapter_id, page_number, total_pages)
        VALUES ('tg_user_1', ?, ?, 5, 20)
        """,
        (m1, ch1),
    )
    test_db.commit()

    # Get history: should automatically backfill cover from matching title row
    history = service.get_user_history("tg_user_1")
    assert len(history) == 1
    assert history[0].cover_url == "https://uploads.mangadex.org/cover.jpg"
