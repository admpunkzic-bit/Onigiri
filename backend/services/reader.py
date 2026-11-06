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
from urllib.parse import urlsplit, urljoin

import httpx
from fastapi import HTTPException

from providers.base import ProviderPagesResult
from providers.registry import ProviderRegistry
from schemas.manga import (
    ChapterReaderDetailRead,
    ChapterReaderPageItem,
    ReadingHistoryItemRead,
    ReadingProgressRead,
)

logger = logging.getLogger(__name__)

# Allowed domain suffixes for SSRF protection
ALLOWED_DOMAINS = (
    ".mangadex.network",
    "uploads.mangadex.org",
    ".manga-chan.me",
    "manga-chan.me",
)

# In-memory AtHome cache: source_chapter_id -> { "result": ProviderPagesResult, "cached_at": float }
_ATHOME_CACHE: Dict[str, Dict[str, Any]] = {}
ATHOME_CACHE_TTL_SECONDS = 600.0  # 10 minutes TTL

# SingleFlight concurrency deduplication: cache_key -> asyncio.Task
_ATHOME_IN_FLIGHT: Dict[str, asyncio.Task] = {}
_ATHOME_LOCK = asyncio.Lock()


def validate_and_resolve_url_ssrf(target_url: str) -> str:
    """
    Validate target URL against SSRF vulnerabilities:
    - Auto-upgrades HTTP scheme to HTTPS for allowlisted domains.
    - Hostname must strictly match authorized MangaDex and Manga-Chan domains.
    - No credentials (user:pass@) in URL.
    - DNS resolution must not resolve to loopback, private, link-local,
      cloud metadata (169.254.169.254), multicast, or reserved IPs.
    Returns the normalized HTTPS URL string.
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
            detail=f"SSRF protection: Domain '{hostname}' is not in authorized CDN network",
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

    return clean_url


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
        provider_id: str = "mangadex",
    ) -> ProviderPagesResult:
        """
        Fetch AtHome pages from registered provider with in-memory 10-minute caching
        and SingleFlight concurrency deduplication.
        """
        now = time.time()
        cache_key = f"{provider_id}_{source_chapter_id}_{data_saver}"

        if not force_refresh and cache_key in _ATHOME_CACHE:
            entry = _ATHOME_CACHE[cache_key]
            if (now - entry["cached_at"]) < ATHOME_CACHE_TTL_SECONDS:
                return entry["result"]

        if not self.registry:
            raise HTTPException(status_code=500, detail="Provider registry not available")

        # SingleFlight: reuse in-flight task for concurrent requests to same chapter
        async with _ATHOME_LOCK:
            # Re-check cache under lock
            if not force_refresh and cache_key in _ATHOME_CACHE:
                entry = _ATHOME_CACHE[cache_key]
                if (time.time() - entry["cached_at"]) < ATHOME_CACHE_TTL_SECONDS:
                    return entry["result"]

            task = _ATHOME_IN_FLIGHT.get(cache_key)
            if task is None:
                task = asyncio.create_task(
                    self._execute_athome_fetch(source_chapter_id, data_saver, cache_key, provider_id)
                )
                _ATHOME_IN_FLIGHT[cache_key] = task

        # Await shielded task so client disconnects do not cancel the in-flight worker
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            raise

    async def _execute_athome_fetch(
        self,
        source_chapter_id: str,
        data_saver: bool,
        cache_key: str,
        provider_id: str = "mangadex",
    ) -> ProviderPagesResult:
        """
        Execute AtHome provider fetch, update cache, and ensure cleanup from in-flight map.
        """
        provider = self.registry.get(provider_id)
        try:
            result = await provider.get_chapter_pages(
                provider_chapter_id=source_chapter_id,
                data_saver=data_saver,
            )
            _ATHOME_CACHE[cache_key] = {
                "result": result,
                "cached_at": time.time(),
            }
            return result
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(
                "Failed to load pages for chapter %s from provider %s: %s",
                source_chapter_id,
                provider_id,
                exc,
            )
            raise HTTPException(status_code=502, detail=f"Remote provider error: {exc}") from exc
        finally:
            async with _ATHOME_LOCK:
                _ATHOME_IN_FLIGHT.pop(cache_key, None)

    async def get_chapter_reader_detail(
        self,
        id_or_slug: str,
        chapter_id: int,
        enable_mangadex: bool = True,
    ) -> ChapterReaderDetailRead:
        """
        Get metadata, ordered pages list, and adjacent chapter pointers for the reader.
        Respects enable_mangadex toggle for primary and fallback attempts.
        """
        cursor = self.conn.cursor()

        # Find manga by id or slug
        clean_id = id_or_slug.strip()
        cursor.execute("SELECT id, title, slug, cover_url FROM manga WHERE id = ? OR slug = ?", (clean_id, clean_id))
        manga_row = cursor.fetchone()
        if not manga_row:
            raise HTTPException(status_code=404, detail="Manga not found")

        manga_id = manga_row["id"]
        manga_title = manga_row["title"]
        manga_slug = manga_row["slug"]
        cover_url = manga_row["cover_url"]

        # Find chapter and ensure it belongs to this manga
        cursor.execute(
            """
            SELECT c.id, c.manga_id, c.source_chapter_id, c.canonical_chapter_id, c.chapter_number, c.volume_number,
                   c.title, c.language, c.scanlation_group, ms.source_name
            FROM chapters c
            LEFT JOIN manga_sources ms ON ms.id = c.manga_source_id
            WHERE c.id = ? AND c.manga_id = ?
            """,
            (chapter_id, manga_id),
        )
        ch_row = cursor.fetchone()
        if not ch_row:
            raise HTTPException(status_code=404, detail="Chapter not found for this manga")

        if ch_row["language"] != "ru":
            raise HTTPException(status_code=400, detail="Only Russian chapters are supported")

        source_ch_id = ch_row["source_chapter_id"]
        provider_id = ch_row["source_name"] or "mangadex"
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

        # Fetch fresh/cached AtHome pages (with automated transparent fallback)
        athome_res = None
        actual_chapter_id = chapter_id
        actual_provider_id = provider_id
        actual_source_ch_id = source_ch_id

        can_try_primary = not (provider_id == "mangadex" and not enable_mangadex)
        if can_try_primary:
            try:
                athome_res = await self.get_athome_pages(
                    source_ch_id, data_saver=False, provider_id=provider_id
                )
                if not athome_res.pages:
                    raise ValueError("Provider returned 0 pages")
            except Exception as primary_err:
                logger.warning(
                    "Primary fetch for chapter %d (source %s, %s) failed: %s. Looking for fallback...",
                    chapter_id, source_ch_id, provider_id, primary_err
                )

        if not athome_res or not athome_res.pages:
            cursor.execute(
                """
                SELECT c.id, c.source_chapter_id, ms.source_name
                FROM chapters c
                LEFT JOIN manga_sources ms ON ms.id = c.manga_source_id
                WHERE c.manga_id = ? 
                  AND c.id != ?
                  AND (
                    (c.canonical_chapter_id IS NOT NULL AND c.canonical_chapter_id = ?)
                    OR (c.chapter_number = ?)
                  )
                  AND c.source_chapter_id IS NOT NULL
                  AND c.language = 'ru'
                ORDER BY c.id ASC
                """,
                (manga_id, chapter_id, ch_row["canonical_chapter_id"], ch_row["chapter_number"]),
            )
            candidates = cursor.fetchall()
            for cand in candidates:
                cand_source_id = cand["source_chapter_id"]
                cand_provider = cand["source_name"] or ("mangadex" if provider_id == "mangachan" else "mangachan")
                if cand_provider == "mangadex" and not enable_mangadex:
                    continue
                try:
                    alt_res = await self.get_athome_pages(
                        cand_source_id, data_saver=False, provider_id=cand_provider
                    )
                    if alt_res and alt_res.pages:
                        logger.info(
                            "Transparent fallback: chapter %d -> alternative %d (%s) with %d pages",
                            chapter_id, cand["id"], cand_provider, len(alt_res.pages)
                        )
                        athome_res = alt_res
                        actual_chapter_id = cand["id"]
                        actual_provider_id = cand_provider
                        actual_source_ch_id = cand_source_id
                        break
                except Exception as cand_err:
                    logger.debug("Alternative candidate %d failed: %s", cand["id"], cand_err)

            if not athome_res or not athome_res.pages:
                if provider_id == "mangadex" and not enable_mangadex:
                    raise HTTPException(status_code=403, detail="Источник MangaDex отключён в настройках")
                raise HTTPException(status_code=502, detail="Не удалось загрузить страницы главы ни из одного источника")

        pages = [
            ChapterReaderPageItem(
                page_number=p.page_number,
                image_url=f"/api/manga/chapters/{actual_chapter_id}/pages/{p.page_number}",
            )
            for p in athome_res.pages
        ]

        return ChapterReaderDetailRead(
            chapter_id=ch_row["id"],
            manga_id=manga_id,
            manga_title=manga_title,
            cover_url=cover_url,
            manga_slug=manga_slug or str(manga_id),
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
        enable_mangadex: bool = True,
    ) -> Tuple[bytes, str]:
        """
        Securely stream a specific page image by resolving its URL on backend.
        Validates target URL against SSRF, validates redirects, injects Referer for Manga-Chan,
        and sniffs Content-Type (supporting AVIF, WEBP, PNG, JPEG).
        Respects enable_mangadex toggle and falls back across providers and dataSaver modes.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT c.id, c.manga_id, c.source_chapter_id, c.canonical_chapter_id, c.chapter_number, c.language, ms.source_name
            FROM chapters c
            LEFT JOIN manga_sources ms ON ms.id = c.manga_source_id
            WHERE c.id = ?
            """,
            (chapter_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Chapter not found")

        if row["language"] != "ru":
            raise HTTPException(status_code=400, detail="Only Russian chapters are permitted")

        source_ch_id = row["source_chapter_id"]
        provider_id = row["source_name"] or "mangadex"
        if not source_ch_id:
            raise HTTPException(status_code=404, detail="Source chapter ID missing")

        # Find all fallback candidate chapters in case primary source fails
        cursor.execute(
            """
            SELECT c.id, c.source_chapter_id, ms.source_name
            FROM chapters c
            LEFT JOIN manga_sources ms ON ms.id = c.manga_source_id
            WHERE c.manga_id = ?
              AND c.id != ?
              AND (
                (c.canonical_chapter_id IS NOT NULL AND c.canonical_chapter_id = ?)
                OR (c.chapter_number = ?)
              )
              AND c.source_chapter_id IS NOT NULL
              AND c.language = 'ru'
            ORDER BY c.id ASC
            """,
            (row["manga_id"], chapter_id, row["canonical_chapter_id"], row["chapter_number"]),
        )
        alternative_chapters = cursor.fetchall()

        # Build candidate queue: primary first, then alternatives (respecting enable_mangadex)
        candidates = []
        if not (provider_id == "mangadex" and not enable_mangadex):
            candidates.append((source_ch_id, provider_id))

        for alt in alternative_chapters:
            alt_prov = alt["source_name"] or ("mangadex" if provider_id == "mangachan" else "mangachan")
            if alt_prov == "mangadex" and not enable_mangadex:
                continue
            candidates.append((alt["source_chapter_id"], alt_prov))

        if not candidates:
            if provider_id == "mangadex" and not enable_mangadex:
                raise HTTPException(status_code=403, detail="Источник MangaDex отключён в настройках")
            raise HTTPException(status_code=404, detail="No eligible chapter source found")

        last_error = None
        for current_ch_id, current_prov in candidates:
            try:
                athome_res = await self.get_athome_pages(
                    current_ch_id, data_saver=data_saver, provider_id=current_prov
                )
                if not (1 <= page_number <= len(athome_res.pages)):
                    raise HTTPException(
                        status_code=404,
                        detail=f"Page number {page_number} out of bounds (1-{len(athome_res.pages)})",
                    )

                raw_target_url = athome_res.pages[page_number - 1].image_url
                if raw_target_url.startswith("http://"):
                    raw_target_url = "https://" + raw_target_url[7:]
                target_url = validate_and_resolve_url_ssrf(raw_target_url)

                req_headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Onigiri-App/1.0"
                }
                if current_prov == "mangachan" or ".manga-chan.me" in target_url:
                    req_headers["Referer"] = f"https://im.manga-chan.me/online/{current_ch_id}.html"

                async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
                    current_url = target_url
                    max_redirects = 5
                    redirect_count = 0
                    resp = None

                    while redirect_count < max_redirects:
                        resp = await client.get(current_url, headers=req_headers)

                        # If MangaDex@Home node returned 404/502/504, perform automated token refresh and data-saver fallback
                        if current_prov == "mangadex" and resp.status_code in (404, 502, 504) and redirect_count == 0:
                            logger.info("AtHome node returned %d for %s (data_saver=%s), refreshing server token...", resp.status_code, current_ch_id, data_saver)
                            fresh_res = await self.get_athome_pages(
                                current_ch_id, data_saver=data_saver, force_refresh=True, provider_id=current_prov
                            )
                            if 1 <= page_number <= len(fresh_res.pages):
                                fresh_url = fresh_res.pages[page_number - 1].image_url
                                if fresh_url.startswith("http://"):
                                    fresh_url = "https://" + fresh_url[7:]
                                current_url = validate_and_resolve_url_ssrf(fresh_url)
                                resp = await client.get(current_url, headers=req_headers)

                            # If still failing and we were requesting full resolution, fall back to dataSaver
                            if resp.status_code in (404, 502, 504) and not data_saver:
                                logger.info("AtHome node still returned %d, falling back to data_saver=True for %s", resp.status_code, current_ch_id)
                                saver_res = await self.get_athome_pages(
                                    current_ch_id, data_saver=True, force_refresh=False, provider_id=current_prov
                                )
                                if 1 <= page_number <= len(saver_res.pages):
                                    saver_url = saver_res.pages[page_number - 1].image_url
                                    if saver_url.startswith("http://"):
                                        saver_url = "https://" + saver_url[7:]
                                    current_url = validate_and_resolve_url_ssrf(saver_url)
                                    resp = await client.get(current_url, headers=req_headers)

                        # Safe redirect handling with full SSRF re-validation and urljoin for relative targets
                        if resp.status_code in (301, 302, 303, 307, 308):
                            redirect_target = resp.headers.get("location")
                            if not redirect_target:
                                raise HTTPException(status_code=502, detail="SSRF protection: Redirect without Location header")
                            resolved_target = urljoin(current_url, redirect_target)
                            if resolved_target.startswith("http://"):
                                resolved_target = "https://" + resolved_target[7:]
                            current_url = validate_and_resolve_url_ssrf(resolved_target)
                            redirect_count += 1
                            continue

                        break

                    if not resp or resp.status_code != 200:
                        code = resp.status_code if resp else 502
                        raise HTTPException(
                            status_code=code,
                            detail=f"Failed to fetch page from image server (HTTP {code})",
                        )

                    raw_bytes = resp.content
                    if len(raw_bytes) > 15 * 1024 * 1024:
                        raise HTTPException(status_code=502, detail="Image payload exceeds 15MB limit")

                    content_type = resp.headers.get("content-type", "image/jpeg")

                    # Sniff binary magic bytes for image formats
                    if len(raw_bytes) >= 12 and raw_bytes[4:12] == b"ftypavif":
                        content_type = "image/avif"
                    elif len(raw_bytes) >= 3 and raw_bytes[:3] == b"\xff\xd8\xff":
                        content_type = "image/jpeg"
                    elif len(raw_bytes) >= 8 and raw_bytes[:8] == b"\x89PNG\r\n\x1a\n":
                        content_type = "image/png"
                    elif len(raw_bytes) >= 12 and raw_bytes[:4] == b"RIFF" and raw_bytes[8:12] == b"WEBP":
                        content_type = "image/webp"

                    return raw_bytes, content_type

            except Exception as exc:
                logger.warning("Error fetching chapter page (%s, %s): %s", current_prov, current_ch_id, exc)
                last_error = exc
                continue

        if last_error:
            if isinstance(last_error, HTTPException):
                raise last_error
            raise HTTPException(status_code=502, detail=f"Image delivery failed across available providers: {last_error}")
        raise HTTPException(status_code=502, detail="No valid image stream could be established")

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

    def get_user_history(self, user_id: str) -> List[ReadingHistoryItemRead]:
        """
        Get ordered reading history for a verified Telegram user.
        Includes manga info, cover, chapter info, page progress, and timestamps.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT 
                p.manga_id,
                m.slug AS manga_slug,
                m.title AS manga_title,
                m.cover_url,
                m.status AS manga_status,
                p.chapter_id,
                c.chapter_number,
                c.volume_number,
                c.title AS chapter_title,
                p.page_number,
                p.total_pages,
                p.updated_at
            FROM user_reading_progress p
            JOIN manga m ON m.id = p.manga_id
            JOIN chapters c ON c.id = p.chapter_id
            WHERE p.user_id = ?
            ORDER BY p.updated_at DESC, p.id DESC
            """,
            (user_id,),
        )
        rows = cursor.fetchall()
        items: List[ReadingHistoryItemRead] = []
        for r in rows:
            cover = r["cover_url"]
            if not cover:
                cursor.execute(
                    """
                    SELECT cover_url FROM manga
                    WHERE (title = ? OR slug = ?) AND cover_url IS NOT NULL AND cover_url != ''
                    LIMIT 1
                    """,
                    (r["manga_title"], r["manga_slug"]),
                )
                alt_cover_row = cursor.fetchone()
                if alt_cover_row:
                    cover = alt_cover_row["cover_url"]

            items.append(
                ReadingHistoryItemRead(
                    manga_id=r["manga_id"],
                    manga_slug=r["manga_slug"] or str(r["manga_id"]),
                    manga_title=r["manga_title"],
                    cover_url=cover,
                    manga_status=r["manga_status"] or "unknown",
                    chapter_id=r["chapter_id"],
                    chapter_number=float(r["chapter_number"]) if r["chapter_number"] is not None else None,
                    volume_number=r["volume_number"],
                    chapter_title=r["chapter_title"],
                    page_number=r["page_number"],
                    total_pages=r["total_pages"],
                    updated_at=str(r["updated_at"]),
                )
            )
        return items

    def delete_user_history_item(self, user_id: str, manga_id_or_slug: str) -> bool:
        """
        Remove a specific manga from user reading history.
        """
        cursor = self.conn.cursor()
        clean = manga_id_or_slug.strip()
        cursor.execute("SELECT id FROM manga WHERE id = ? OR slug = ?", (clean, clean))
        m_row = cursor.fetchone()
        if m_row:
            target_manga_id = m_row["id"]
        elif clean.isdigit():
            target_manga_id = int(clean)
        else:
            return False

        cursor.execute(
            "DELETE FROM user_reading_progress WHERE user_id = ? AND manga_id = ?",
            (user_id, target_manga_id),
        )
        deleted = cursor.rowcount > 0
        self.conn.commit()
        return deleted

    def clear_user_history(self, user_id: str) -> int:
        """
        Clear all reading history for a verified Telegram user.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "DELETE FROM user_reading_progress WHERE user_id = ?",
            (user_id,),
        )
        count = cursor.rowcount
        self.conn.commit()
        return count
