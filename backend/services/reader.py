"""
Reader Service for Onigiri.
Coordinates AtHome page resolution, SSRF-protected page streaming,
adjacent chapter navigation, and Telegram user reading progress persistence.
"""

import asyncio
import ipaddress
import logging
import socket
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from providers.base import ProviderPagesResult
from providers.registry import ProviderRegistry
from schemas.manga import (
    ChapterReaderDetailRead,
    ChapterReaderPageItem,
    ReadingProgressRead,
)

logger = logging.getLogger(__name__)

# Allowed MangaDex domain suffixes for SSRF protection
ALLOWED_DOMAINS = (".mangadex.network", "uploads.mangadex.org")

# In-memory AtHome cache: source_chapter_id -> { "result": ProviderPagesResult, "cached_at": float }
_ATHOME_CACHE: Dict[str, Dict[str, Any]] = {}
ATHOME_CACHE_TTL_SECONDS = 600.0  # 10 minutes TTL


def validate_and_resolve_url_ssrf(target_url: str) -> None:
    """
    Validate target URL against SSRF vulnerabilities:
    - Scheme must be strictly HTTPS.
    - Hostname must strictly match authorized MangaDex domains.
    - No credentials (user:pass@) in URL.
    - DNS resolution must not resolve to loopback, private, link-local,
      cloud metadata (169.254.169.254), multicast, or reserved IPs.
    """
    if not isinstance(target_url, str) or not target_url.strip():
        raise HTTPException(status_code=400, detail="Invalid target URL: empty or missing")

    clean_url = target_url.strip()
    try:
        parsed = urlsplit(clean_url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Malformed URL: {exc}") from exc

    if parsed.scheme.lower() != "https":
        raise HTTPException(status_code=400, detail="SSRF protection: Only HTTPS scheme is permitted")

    hostname = (parsed.hostname or "").lower().strip()
    if not hostname:
        raise HTTPException(status_code=400, detail="SSRF protection: Missing hostname")

    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="SSRF protection: URL credentials are not allowed")

    # Domain allowlist check
    is_allowed_domain = any(
        hostname == allowed or hostname.endswith(allowed) for allowed in ALLOWED_DOMAINS
    )
    if not is_allowed_domain:
        raise HTTPException(
            status_code=403,
            detail=f"SSRF protection: Domain '{hostname}' is not in authorized MangaDex network",
        )

    # DNS Resolution and IP Address Filtering (Prevent DNS Rebinding / Intranet probing)
    port = parsed.port or 443
    try:
        addr_info = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DNS resolution failed for '{hostname}': {exc}") from exc

    if not addr_info:
        raise HTTPException(status_code=502, detail=f"No DNS records found for host '{hostname}'")

    for item in addr_info:
        ip_str = item[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=f"Invalid IP address format '{ip_str}'") from exc

        # Disallow loopback, private RFC1918, link-local (cloud metadata 169.254.169.254), etc.
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            logger.warning("SSRF blocked: host '%s' resolved to forbidden IP '%s'", hostname, ip_str)
            raise HTTPException(
                status_code=403,
                detail=f"SSRF protection: Connection to private or restricted IP '{ip_str}' is forbidden",
            )


class ReaderService:
    """
    Handles chapter page retrieval, adjacent chapter computation,
    secure image proxying, and user reading progress management.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        registry: Optional[ProviderRegistry] = None,
    ) -> None:
        self.conn = conn
        self.registry = registry

    async def get_athome_pages(
        self,
        source_chapter_id: str,
        data_saver: bool = False,
        force_refresh: bool = False,
    ) -> ProviderPagesResult:
        """
        Fetch AtHome pages from registered provider with in-memory 10-minute caching.
        """
        now = time.time()
        cache_key = f"{source_chapter_id}_{data_saver}"

        if not force_refresh and cache_key in _ATHOME_CACHE:
            entry = _ATHOME_CACHE[cache_key]
            if (now - entry["cached_at"]) < ATHOME_CACHE_TTL_SECONDS:
                return entry["result"]

        if not self.registry:
            raise HTTPException(status_code=500, detail="Provider registry not available")

        provider = self.registry.get("mangadex")
        try:
            result = await provider.get_chapter_pages(
                provider_chapter_id=source_chapter_id,
                data_saver=data_saver,
            )
        except Exception as exc:
            logger.error("Failed to load AtHome pages for chapter %s: %s", source_chapter_id, exc)
            raise HTTPException(status_code=502, detail=f"Remote provider error: {exc}") from exc

        _ATHOME_CACHE[cache_key] = {
            "result": result,
            "cached_at": now,
        }
        return result

    async def get_chapter_reader_detail(
        self,
        id_or_slug: str,
        chapter_id: int,
    ) -> ChapterReaderDetailRead:
        """
        Get metadata, ordered pages list, and adjacent chapter pointers for the reader.
        """
        cursor = self.conn.cursor()

        # Find manga by id or slug
        clean_id = id_or_slug.strip()
        cursor.execute("SELECT id, title, slug FROM manga WHERE id = ? OR slug = ?", (clean_id, clean_id))
        manga_row = cursor.fetchone()
        if not manga_row:
            raise HTTPException(status_code=404, detail="Manga not found")

        manga_id = manga_row["id"]
        manga_title = manga_row["title"]

        # Find chapter and ensure it belongs to this manga
        cursor.execute(
            """
            SELECT id, manga_id, source_chapter_id, chapter_number, volume_number,
                   title, language, scanlation_group
            FROM chapters
            WHERE id = ? AND manga_id = ?
            """,
            (chapter_id, manga_id),
        )
        ch_row = cursor.fetchone()
        if not ch_row:
            raise HTTPException(status_code=404, detail="Chapter not found for this manga")

        if ch_row["language"] != "ru":
            raise HTTPException(status_code=400, detail="Only Russian chapters are supported")

        source_ch_id = ch_row["source_chapter_id"]
        if not source_ch_id:
            raise HTTPException(status_code=404, detail="Source chapter ID not configured")

        # Load all Russian chapters for this manga to compute adjacent chapter navigation
        cursor.execute(
            """
            SELECT id, chapter_number
            FROM chapters
            WHERE manga_id = ? AND language = 'ru'
            ORDER BY chapter_number ASC, id ASC
            """,
            (manga_id,),
        )
        all_chapters = cursor.fetchall()

        prev_chapter_id: Optional[int] = None
        next_chapter_id: Optional[int] = None

        current_idx = -1
        for idx, row in enumerate(all_chapters):
            if row["id"] == chapter_id:
                current_idx = idx
                break

        if current_idx != -1:
            if current_idx > 0:
                prev_chapter_id = all_chapters[current_idx - 1]["id"]
            if current_idx < len(all_chapters) - 1:
                next_chapter_id = all_chapters[current_idx + 1]["id"]

        # Fetch fresh/cached AtHome pages
        athome_res = await self.get_athome_pages(source_ch_id, data_saver=False)

        pages = [
            ChapterReaderPageItem(
                page_number=p.page_number,
                image_url=f"/api/manga/chapters/{chapter_id}/pages/{p.page_number}",
            )
            for p in athome_res.pages
        ]

        return ChapterReaderDetailRead(
            chapter_id=ch_row["id"],
            manga_id=manga_id,
            manga_title=manga_title,
            chapter_number=float(ch_row["chapter_number"]) if ch_row["chapter_number"] is not None else None,
            volume_number=ch_row["volume_number"],
            title=ch_row["title"],
            scanlation_group=ch_row["scanlation_group"],
            total_pages=len(pages),
            pages=pages,
            prev_chapter_id=prev_chapter_id,
            next_chapter_id=next_chapter_id,
        )

    async def get_page_image_stream(
        self,
        chapter_id: int,
        page_number: int,
        data_saver: bool = False,
    ) -> Tuple[bytes, str]:
        """
        Securely stream a specific page image by resolving its AtHome URL on backend.
        Validates target URL against SSRF and forbids redirects.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT source_chapter_id, language FROM chapters WHERE id = ?",
            (chapter_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Chapter not found")

        if row["language"] != "ru":
            raise HTTPException(status_code=400, detail="Only Russian chapters are permitted")

        source_ch_id = row["source_chapter_id"]
        if not source_ch_id:
            raise HTTPException(status_code=404, detail="Source chapter ID missing")

        # Resolve pages (with automatic retry / refresh if expired)
        athome_res = await self.get_athome_pages(source_ch_id, data_saver=data_saver)

        if not (1 <= page_number <= len(athome_res.pages)):
            raise HTTPException(
                status_code=404,
                detail=f"Page number {page_number} out of bounds (1-{len(athome_res.pages)})",
            )

        target_url = athome_res.pages[page_number - 1].image_url

        # Enhanced SSRF protection validation
        validate_and_resolve_url_ssrf(target_url)

        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
                resp = await client.get(target_url, headers={"User-Agent": "Onigiri-App/1.0"})

                # If MangaDex@Home token expired (404/504), refresh AtHome server once and retry
                if resp.status_code in (404, 502, 504):
                    logger.info("AtHome node returned %d, refreshing server token for %s", resp.status_code, source_ch_id)
                    fresh_res = await self.get_athome_pages(source_ch_id, data_saver=data_saver, force_refresh=True)
                    if 1 <= page_number <= len(fresh_res.pages):
                        target_url = fresh_res.pages[page_number - 1].image_url
                        validate_and_resolve_url_ssrf(target_url)
                        resp = await client.get(target_url, headers={"User-Agent": "Onigiri-App/1.0"})

                if resp.status_code in (301, 302, 307, 308):
                    raise HTTPException(status_code=502, detail="SSRF protection: Remote server attempted redirect")

                if resp.status_code != 200:
                    raise HTTPException(
                        status_code=resp.status_code,
                        detail=f"Failed to fetch page from image server (HTTP {resp.status_code})",
                    )

                content_type = resp.headers.get("content-type", "image/jpeg")
                return resp.content, content_type

        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"Remote network error: {exc}") from exc

    def get_user_progress(
        self,
        user_id: str,
        id_or_slug: str,
    ) -> Optional[ReadingProgressRead]:
        """
        Get saved reading progress for a verified user and manga.
        """
        cursor = self.conn.cursor()
        clean_id = id_or_slug.strip()

        cursor.execute(
            """
            SELECT p.manga_id, p.chapter_id, p.page_number, p.total_pages, p.updated_at,
                   c.chapter_number, c.title AS chapter_title
            FROM user_reading_progress p
            JOIN manga m ON m.id = p.manga_id
            JOIN chapters c ON c.id = p.chapter_id
            WHERE p.user_id = ? AND (m.id = ? OR m.slug = ?)
            """,
            (user_id, clean_id, clean_id),
        )
        row = cursor.fetchone()
        if not row:
            return None

        return ReadingProgressRead(
            manga_id=row["manga_id"],
            chapter_id=row["chapter_id"],
            chapter_number=float(row["chapter_number"]) if row["chapter_number"] is not None else None,
            chapter_title=row["chapter_title"],
            page_number=row["page_number"],
            total_pages=row["total_pages"],
            updated_at=str(row["updated_at"]),
        )

    def save_user_progress(
        self,
        user_id: str,
        id_or_slug: str,
        chapter_id: int,
        page_number: int,
        total_pages: Optional[int] = None,
    ) -> ReadingProgressRead:
        """
        Upsert reading progress for a verified user and manga.
        """
        cursor = self.conn.cursor()
        clean_id = id_or_slug.strip()

        # Find manga
        cursor.execute("SELECT id FROM manga WHERE id = ? OR slug = ?", (clean_id, clean_id))
        m_row = cursor.fetchone()
        if not m_row:
            raise HTTPException(status_code=404, detail="Manga not found")

        manga_id = m_row["id"]

        # Validate chapter belongs to manga
        cursor.execute(
            "SELECT id, chapter_number, title FROM chapters WHERE id = ? AND manga_id = ?",
            (chapter_id, manga_id),
        )
        ch_row = cursor.fetchone()
        if not ch_row:
            raise HTTPException(status_code=400, detail="Chapter does not belong to this manga")

        cursor.execute(
            """
            INSERT INTO user_reading_progress (
                user_id, manga_id, chapter_id, page_number, total_pages, updated_at
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, manga_id) DO UPDATE SET
                chapter_id = excluded.chapter_id,
                page_number = excluded.page_number,
                total_pages = excluded.total_pages,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, manga_id, chapter_id, max(1, page_number), total_pages),
        )
        self.conn.commit()

        # Fetch and return updated progress
        return self.get_user_progress(user_id, str(manga_id))
