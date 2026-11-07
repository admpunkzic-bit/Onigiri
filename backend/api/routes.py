"""
API routes for Onigiri backend.
Includes health check, unified manga catalog endpoints, and provider inspection endpoints.
"""

import asyncio
import sqlite3
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
import httpx

from database.connection import get_connection
from providers.base import (
    BaseMangaProvider,
    ProviderChapterItem,
    ProviderChaptersResult,
    ProviderError,
    ProviderMangaItem,
    ProviderNetworkError,
    ProviderNotFoundError,
    ProviderPagesResult,
    ProviderRateLimitError,
    ProviderSearchResult,
)
from providers.registry import ProviderRegistry
from api.auth import get_current_telegram_user, require_telegram_user
from schemas.manga import (
    ChapterRead,
    ChapterReaderDetailRead,
    GenreRead,
    HomepageCollectionRead,
    HomepageDataRead,
    MangaDetailRead,
    MangaListRead,
    ReadingHistoryItemRead,
    ReadingProgressRead,
    ReadingProgressUpdate,
)
from services.catalog import CatalogService
from services.reader import ReaderService, validate_and_resolve_url_ssrf

router = APIRouter()


# ==============================================================================
# Dependency Injection
# ==============================================================================

def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Provide a database connection per request with automatic closure."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def get_registry(request: Request) -> ProviderRegistry:
    """Retrieve ProviderRegistry from application state."""
    registry = getattr(request.app.state, "provider_registry", None)
    if not registry:
        raise HTTPException(status_code=500, detail="Provider registry is not initialized")
    return registry


def get_provider(provider_id: str, registry: ProviderRegistry = Depends(get_registry)) -> BaseMangaProvider:
    """Retrieve specific provider by ID or raise 404."""
    try:
        return registry.get(provider_id)
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def get_catalog_service(
    conn: sqlite3.Connection = Depends(get_db),
    registry: ProviderRegistry = Depends(get_registry),
) -> CatalogService:
    """Dependency provider for CatalogService."""
    return CatalogService(conn=conn, registry=registry)


def get_reader_service(
    conn: sqlite3.Connection = Depends(get_db),
    registry: ProviderRegistry = Depends(get_registry),
) -> ReaderService:
    """Dependency provider for ReaderService."""
    return ReaderService(conn=conn, registry=registry)


def get_enable_mangadex(
    request: Request,
    enable_mangadex: Optional[bool] = Query(None, description="Enable or disable MangaDex fallback"),
) -> bool:
    """
    Determine whether MangaDex reserve source and fallback is active.
    Checked via ?enable_mangadex query parameter, then X-Enable-MangaDex header.
    Defaults to True.
    """
    if enable_mangadex is not None:
        return enable_mangadex
    header_val = request.headers.get("x-enable-mangadex")
    if header_val is not None:
        return header_val.strip().lower() in ("1", "true", "yes", "on")
    return True


# ==============================================================================
# Health Check
# ==============================================================================

@router.get("/health")
async def health_check():
    """Return current server status."""
    return {
        "status": "ok",
        "service": "onigiri-api",
        "version": "0.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ==============================================================================
# Homepage & Dynamic Collections (TASK 018)
# ==============================================================================

@router.get("/homepage", response_model=HomepageDataRead)
async def get_homepage(
    guest_manga_ids: Optional[str] = Query(None, description="Comma-separated manga IDs from guest library/history"),
    auth_user: Optional[Dict[str, Any]] = Depends(get_current_telegram_user),
    catalog_service: CatalogService = Depends(get_catalog_service),
    reader_service: ReaderService = Depends(get_reader_service),
):
    """
    Get full dynamic homepage payload in a single high-performance roundtrip:
    - continue_reading (if user has reading progress)
    - for_you (personalized based on library & history genres)
    - popular_ongoing (works currently releasing)
    - popular_completed (finished stories ready to read)
    - recently_updated (titles with fresh Russian chapters)
    - recently_added (newest additions in catalog)
    """
    g_ids: List[int] = []
    if guest_manga_ids:
        for part in guest_manga_ids.split(","):
            try:
                val = int(part.strip())
                if val > 0:
                    g_ids.append(val)
            except ValueError:
                pass

    user_id_str = str(auth_user["id"]) if auth_user and "id" in auth_user else None

    homepage_data = catalog_service.get_homepage_data(
        user_id=user_id_str,
        guest_manga_ids=g_ids,
        limit=12,
    )

    if user_id_str:
        try:
            history_items = reader_service.get_user_history(user_id_str)
            homepage_data.continue_reading = history_items[:6]
        except Exception as exc:
            logger.warning("Error loading continue_reading for user %s: %s", user_id_str, exc)

    return homepage_data


@router.get("/manga/collections/{collection_name}", response_model=HomepageCollectionRead)
async def get_collection(
    collection_name: str,
    guest_manga_ids: Optional[str] = Query(None, description="Comma-separated manga IDs from guest library/history"),
    limit: int = Query(20, ge=1, le=50, description="Items limit"),
    auth_user: Optional[Dict[str, Any]] = Depends(get_current_telegram_user),
    catalog_service: CatalogService = Depends(get_catalog_service),
):
    """
    Get items for a specific dynamic homepage collection.
    Supported collections:
    - popular-completed (popular_completed)
    - popular-ongoing (popular_ongoing)
    - for-you (for_you)
    - recently-added (recently_added)
    - recently-updated (recently_updated)
    """
    c_name = collection_name.lower().replace("-", "_")
    user_id_str = str(auth_user["id"]) if auth_user and "id" in auth_user else None

    g_ids: List[int] = []
    if guest_manga_ids:
        for part in guest_manga_ids.split(","):
            try:
                val = int(part.strip())
                if val > 0:
                    g_ids.append(val)
            except ValueError:
                pass

    if c_name in ("popular_completed", "completed"):
        items = catalog_service.get_popular_completed(limit=limit)
        return HomepageCollectionRead(
            id="popular_completed",
            title="Популярное завершённое",
            subtitle="Завершённые истории, готовые к полному прочтению",
            see_all_url="/search?status=completed&sort_by=popularity",
            items=items,
        )
    elif c_name in ("popular_ongoing", "ongoing"):
        items = catalog_service.get_popular_ongoing(limit=limit)
        return HomepageCollectionRead(
            id="popular_ongoing",
            title="Популярные онгоинги",
            subtitle="Произведения, которые сейчас выходят",
            see_all_url="/search?status=ongoing&sort_by=popularity",
            items=items,
        )
    elif c_name in ("for_you", "personalized", "style"):
        items, is_personalized = catalog_service.get_personalized_recommendations(
            user_id=user_id_str, guest_manga_ids=g_ids, limit=limit
        )
        subtitle = (
            "Подобрано на основе жанров манги из вашей библиотеки и истории чтения"
            if is_personalized
            else "Популярные произведения Onigiri. Читайте или сохраняйте мангу, чтобы настроить рекомендации"
        )
        return HomepageCollectionRead(
            id="for_you",
            title="Манга в вашем стиле",
            subtitle=subtitle,
            see_all_url="/search?sort_by=rating",
            items=items,
        )
    elif c_name in ("recently_added", "new"):
        items = catalog_service.get_recently_added(limit=limit)
        return HomepageCollectionRead(
            id="recently_added",
            title="Недавно добавленные",
            subtitle="Новинки в каталоге Onigiri",
            see_all_url="/search?sort_by=created_at",
            items=items,
        )
    elif c_name in ("recently_updated", "updated"):
        items = catalog_service.get_recently_updated(limit=limit)
        return HomepageCollectionRead(
            id="recently_updated",
            title="Недавно обновлённые",
            subtitle="Произведения со свежими русскими главами",
            see_all_url="/search?sort_by=updated_at",
            items=items,
        )
    else:
        raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' not found")


# ==============================================================================
# Unified Catalog Endpoints (Onigiri User-Facing API)
# ==============================================================================

@router.get("/manga/genres", response_model=List[GenreRead])
async def get_all_genres(
    catalog_service: CatalogService = Depends(get_catalog_service),
):
    """
    Get all active manga genres in the Onigiri catalog for filter selection.
    """
    return catalog_service.get_all_genres()


@router.get("/manga/search", response_model=List[MangaListRead])
async def search_manga(
    q: Optional[str] = Query(None, description="Search query string"),
    genre: Optional[List[str]] = Query(None, description="Included genre slugs or names"),
    excluded_genre: Optional[List[str]] = Query(None, description="Excluded genre slugs or names"),
    type: Optional[str] = Query(None, description="Manga format type: manga, manhwa, manhua"),
    status: Optional[str] = Query(None, description="Publication status: ongoing, completed, hiatus, cancelled"),
    author: Optional[str] = Query(None, description="Author or artist name"),
    release_year: Optional[int] = Query(None, description="Release year"),
    sort_by: str = Query("popularity", description="Sort by: popularity, rating, updated_at, created_at, relevance"),
    sort_order: str = Query("desc", description="Sort order: asc, desc"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    enable_mangadex: bool = Depends(get_enable_mangadex),
    catalog_service: CatalogService = Depends(get_catalog_service),
):
    """
    Search and filter manga across the unified Onigiri catalog.
    Supports full-text query, genre inclusion/exclusion, format types, status,
    author/artist, release year, custom sorting, and pagination without exposing provider names.
    Respects enable_mangadex toggle for external fallback searches.
    """
    return await catalog_service.search(
        query=q,
        genres=genre,
        excluded_genres=excluded_genre,
        manga_type=type,
        status=status,
        author=author,
        release_year=release_year,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        limit=limit,
        enable_mangadex=enable_mangadex,
    )


# Helper to sniff binary image magic bytes
def _sniff_image_type(raw_bytes: bytes) -> Optional[str]:
    """Sniff binary magic bytes to determine image MIME type, or None if not an image."""
    if len(raw_bytes) >= 3 and raw_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(raw_bytes) >= 8 and raw_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(raw_bytes) >= 12 and raw_bytes[:4] == b"RIFF" and raw_bytes[8:12] == b"WEBP":
        return "image/webp"
    if len(raw_bytes) >= 6 and (raw_bytes[:6] == b"GIF87a" or raw_bytes[:6] == b"GIF89a"):
        return "image/gif"
    if len(raw_bytes) >= 12 and raw_bytes[4:12] == b"ftypavif":
        return "image/avif"
    return None


# In-memory LRU cache for cover images: URL -> (content_bytes, content_type)
_COVER_CACHE: OrderedDict[str, Tuple[bytes, str]] = OrderedDict()
_MAX_COVER_CACHE_ITEMS = 500
_COVER_CACHE_LOCK = asyncio.Lock()

@router.get("/manga/cover/proxy")
async def get_manga_cover(
    url: str = Query(..., description="External cover image URL"),
    v: Optional[str] = Query(None, description="Cache buster version tag"),
):
    """
    Safely proxy external manga covers to bypass anti-hotlinking and bot-challenge protections.
    Supports in-memory LRU caching to eliminate redundant outbound requests.
    Restricted strictly to authorized MangaDex and Manga-Chan CDN hosts with full SSRF validation.
    """
    clean_url = url.strip()
    if clean_url.startswith("http://"):
        clean_url = "https://" + clean_url[7:]
    try:
        clean_url = validate_and_resolve_url_ssrf(clean_url)
    except HTTPException:
        raise HTTPException(status_code=400, detail="Invalid cover URL: host not permitted")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid cover URL: {exc}")

    async with _COVER_CACHE_LOCK:
        if clean_url in _COVER_CACHE:
            _COVER_CACHE.move_to_end(clean_url)
            cached_content, cached_type = _COVER_CACHE[clean_url]
            # Safety check: ensure cached entry is not HTML, otherwise evict poisoned cache
            if not cached_content.strip().startswith((b"<!DOCTYPE", b"<!doctype", b"<html", b"<HTML")):
                return Response(
                    content=cached_content,
                    media_type=cached_type,
                    headers={
                        "Cache-Control": "public, max-age=86400",
                    },
                )
            else:
                del _COVER_CACHE[clean_url]

    is_mangachan = "manga-chan.me" in clean_url
    is_mangadex = "mangadex.org" in clean_url
    is_remanga = "remanga.org" in clean_url or "reimg2.org" in clean_url
    is_mangalib = (
        "imglib.info" in clean_url
        or "cdnrulib.link" in clean_url
        or "cdnlibs.org" in clean_url
        or "mangalib.me" in clean_url
        or "lib.social" in clean_url
    )

    if is_mangachan:
        req_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://im.manga-chan.me/",
        }
        verify_ssl = False
        follow_redirects = True
    elif is_remanga:
        req_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://remanga.org/",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        verify_ssl = True
        follow_redirects = True
    elif is_mangalib:
        req_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://mangalib.me/",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        verify_ssl = True
        follow_redirects = True
    elif is_mangadex:
        # MangaDex CDN edge requires clean application User-Agent.
        # Chrome User-Agent without session cookies triggers edge/challenge (Cloudflare/POWBlock).
        req_headers = {
            "User-Agent": "Onigiri-App/1.0",
        }
        verify_ssl = True
        follow_redirects = False
    else:
        req_headers = {
            "User-Agent": "Onigiri-App/1.0",
        }
        verify_ssl = True
        follow_redirects = False

    try:
        async with httpx.AsyncClient(timeout=15.0, verify=verify_ssl, follow_redirects=follow_redirects) as client:
            resp = await client.get(clean_url, headers=req_headers)
            if resp.status_code in (301, 302, 303, 307, 308):
                # Anti-bot redirect encountered; do not follow to HTML challenge
                raise HTTPException(status_code=502, detail="Remote host issued unexpected redirect")
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Failed to load cover from remote host")

            content_bytes = resp.content
            if len(content_bytes) > 15 * 1024 * 1024:
                raise HTTPException(status_code=502, detail="Cover image exceeds size limit")

            if content_bytes.strip().startswith((b"<!DOCTYPE", b"<!doctype", b"<html", b"<HTML")):
                raise HTTPException(status_code=502, detail="Remote host returned non-image response")

            # Validate binary magic bytes or explicit image content-type
            sniffed_type = _sniff_image_type(content_bytes)
            if not sniffed_type:
                resp_ct = resp.headers.get("content-type", "")
                if resp_ct.startswith("image/"):
                    sniffed_type = resp_ct
                else:
                    raise HTTPException(status_code=502, detail="Remote host returned non-image response")

            async with _COVER_CACHE_LOCK:
                _COVER_CACHE[clean_url] = (content_bytes, sniffed_type)
                if len(_COVER_CACHE) > _MAX_COVER_CACHE_ITEMS:
                    _COVER_CACHE.popitem(last=False)

            return Response(
                content=content_bytes,
                media_type=sniffed_type,
                headers={
                    "Cache-Control": "public, max-age=86400",
                },
            )
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Remote network error: {exc}")


@router.get("/manga/{id_or_slug}", response_model=MangaDetailRead)
async def get_manga_detail(
    id_or_slug: str,
    translation_id: Optional[str] = Query(None, description="Selected translation variant ID"),
    enable_mangadex: bool = Depends(get_enable_mangadex),
    catalog_service: CatalogService = Depends(get_catalog_service),
):
    """
    Get full manga details by Onigiri ID or slug.
    Returns unified manga card with translation variants and scoped chapters.
    """
    manga = await catalog_service.get_manga_by_id_or_slug(
        id_or_slug, translation_id=translation_id, enable_mangadex=enable_mangadex
    )
    if not manga:
        raise HTTPException(status_code=404, detail="Manga not found")
    return manga


@router.get("/manga/{id_or_slug}/chapters", response_model=List[ChapterRead])
async def get_manga_chapters_list(
    id_or_slug: str,
    order: str = Query("asc", description="Sort order: 'asc' or 'desc'"),
    translation_id: Optional[str] = Query(None, description="Selected translation variant ID"),
    enable_mangadex: bool = Depends(get_enable_mangadex),
    catalog_service: CatalogService = Depends(get_catalog_service),
):
    """
    Get full Russian chapters list for a manga by ID, slug, or external UUID.
    Scoped to the chosen translation variant, sorted by volume and chapter number.
    """
    clean_order = order.lower() if order.lower() in ("asc", "desc") else "asc"
    chapters = await catalog_service.get_chapters_for_manga(
        id_or_slug, order=clean_order, translation_id=translation_id, enable_mangadex=enable_mangadex
    )
    if chapters is None:
        raise HTTPException(status_code=404, detail="Manga not found")
    return chapters


@router.get("/manga/{id_or_slug}/translations")
async def get_manga_translations(
    id_or_slug: str,
    enable_mangadex: bool = Depends(get_enable_mangadex),
    catalog_service: CatalogService = Depends(get_catalog_service),
):
    """
    Get all available translation variants with metrics and default selection for a manga.
    """
    manga = await catalog_service.get_manga_by_id_or_slug(
        id_or_slug, auto_sync_chapters=False, enable_mangadex=enable_mangadex
    )
    if not manga:
        raise HTTPException(status_code=404, detail="Manga not found")
    variants, default_id = catalog_service.get_translation_variants(manga.id, enable_mangadex=enable_mangadex)
    return {
        "manga_id": manga.id,
        "default_translation_id": default_id,
        "translations": variants,
    }


@router.post("/manga/{id_or_slug}/sync")
async def sync_manga_chapters_endpoint(
    id_or_slug: str,
    enable_mangadex: bool = Depends(get_enable_mangadex),
    catalog_service: CatalogService = Depends(get_catalog_service),
):
    """
    Force synchronization of Russian chapters for a manga from external providers.
    Returns count of synced chapters. Idempotent.
    """
    manga = await catalog_service.get_manga_by_id_or_slug(id_or_slug, auto_sync_chapters=False, enable_mangadex=enable_mangadex)
    if not manga:
        raise HTTPException(status_code=404, detail="Manga not found")
    chapters = await catalog_service.sync_manga_chapters(manga.id, enable_mangadex=enable_mangadex)
    return {
        "status": "ok",
        "manga_id": manga.id,
        "chapters_count": len(chapters),
    }


# ==============================================================================
# Reader & Reading Progress Endpoints (TASK 012)
# ==============================================================================

@router.get("/manga/{id_or_slug}/chapters/{chapter_id}/pages", response_model=ChapterReaderDetailRead)
async def get_chapter_reader_pages(
    id_or_slug: str,
    chapter_id: int,
    enable_mangadex: bool = Depends(get_enable_mangadex),
    reader_service: ReaderService = Depends(get_reader_service),
):
    """
    Get reader metadata, ordered pages list, and adjacent chapter navigation pointers.
    All page images use internal Onigiri backend endpoints (/api/manga/chapters/{id}/pages/{n}).
    """
    return await reader_service.get_chapter_reader_detail(id_or_slug, chapter_id, enable_mangadex=enable_mangadex)


@router.get("/manga/chapters/{chapter_id}/pages/{page_number}")
async def get_page_image(
    chapter_id: int,
    page_number: int,
    data_saver: bool = Query(False, description="Use dataSaver compressed image"),
    v: Optional[str] = Query(None, description="Cache buster version tag"),
    enable_mangadex: bool = Depends(get_enable_mangadex),
    reader_service: ReaderService = Depends(get_reader_service),
):
    """
    Securely stream a specific chapter page image via backend.
    SSRF-protected, forbids redirects, hides external provider domains.
    """
    image_bytes, content_type = await reader_service.get_page_image_stream(
        chapter_id=chapter_id,
        page_number=page_number,
        data_saver=data_saver,
        enable_mangadex=enable_mangadex,
    )
    return Response(
        content=image_bytes,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=86400",
        },
    )


@router.get("/manga/{id_or_slug}/progress", response_model=Optional[ReadingProgressRead])
async def get_reading_progress(
    id_or_slug: str,
    translation_id: Optional[str] = Query(None, description="Translation variant ID"),
    user: dict = Depends(require_telegram_user),
    reader_service: ReaderService = Depends(get_reader_service),
):
    """
    Get reading progress for a verified Telegram user on a given manga, optionally for a translation variant.
    Requires cryptographically verified Telegram initData.
    """
    return reader_service.get_user_progress(str(user["id"]), id_or_slug, translation_id=translation_id)


@router.post("/manga/{id_or_slug}/progress", response_model=ReadingProgressRead)
async def save_reading_progress(
    id_or_slug: str,
    progress: ReadingProgressUpdate,
    user: dict = Depends(require_telegram_user),
    reader_service: ReaderService = Depends(get_reader_service),
):
    """
    Save reading progress (chapter and page) for a verified Telegram user.
    Requires cryptographically verified Telegram initData.
    """
    return reader_service.save_user_progress(
        user_id=str(user["id"]),
        id_or_slug=id_or_slug,
        chapter_id=progress.chapter_id,
        page_number=progress.page_number,
        total_pages=progress.total_pages,
        translation_id=progress.translation_id,
    )


# ==============================================================================
# Personal Manga Library Endpoints (TASK 013)
# ==============================================================================

@router.get("/library", response_model=List[MangaListRead])
async def get_user_library(
    user: dict = Depends(require_telegram_user),
    catalog_service: CatalogService = Depends(get_catalog_service),
):
    """
    Get all manga saved in personal library for verified Telegram user.
    Results are ordered by save date descending.
    """
    return catalog_service.get_user_library(str(user["id"]))


@router.get("/library/ids", response_model=List[int])
async def get_user_library_ids(
    user: dict = Depends(require_telegram_user),
    catalog_service: CatalogService = Depends(get_catalog_service),
):
    """
    Get lightweight list of manga IDs saved in personal library.
    Used for instant star badge resolution on search and catalog grids.
    """
    return catalog_service.get_user_library_manga_ids(str(user["id"]))


@router.post("/library/{id_or_slug}")
async def add_to_user_library(
    id_or_slug: str,
    user: dict = Depends(require_telegram_user),
    catalog_service: CatalogService = Depends(get_catalog_service),
):
    """
    Add a manga to personal library for verified Telegram user.
    Does not require reading availability or chapters to exist.
    """
    item = await catalog_service.add_to_library(str(user["id"]), id_or_slug)
    if not item:
        raise HTTPException(status_code=404, detail="Manga not found")
    return {"status": "added", "manga_id": item.id, "manga": item}


@router.delete("/library/{id_or_slug}")
async def remove_from_user_library(
    id_or_slug: str,
    user: dict = Depends(require_telegram_user),
    catalog_service: CatalogService = Depends(get_catalog_service),
):
    """
    Remove a manga from personal library for verified Telegram user.
    """
    removed = catalog_service.remove_from_library(str(user["id"]), id_or_slug)
    return {"status": "removed" if removed else "not_found", "removed": removed}


# ==============================================================================
# Reading History Endpoints (TASK 014 Phase 3)
# ==============================================================================

@router.get("/history", response_model=List[ReadingHistoryItemRead])
async def get_reading_history(
    user: dict = Depends(require_telegram_user),
    reader_service: ReaderService = Depends(get_reader_service),
):
    """
    Get ordered reading history for verified Telegram user.
    Uses existing user_reading_progress table and returns manga info, cover, chapter, and progress.
    """
    return reader_service.get_user_history(str(user["id"]))


@router.delete("/history/{manga_id}")
async def delete_history_item(
    manga_id: str,
    user: dict = Depends(require_telegram_user),
    reader_service: ReaderService = Depends(get_reader_service),
):
    """
    Remove a specific manga from reading history for verified Telegram user.
    """
    deleted = reader_service.delete_user_history_item(str(user["id"]), manga_id)
    return {"status": "deleted" if deleted else "not_found", "deleted": deleted}


@router.delete("/history")
async def clear_history(
    user: dict = Depends(require_telegram_user),
    reader_service: ReaderService = Depends(get_reader_service),
):
    """
    Clear all reading history for verified Telegram user.
    """
    deleted_count = reader_service.clear_user_history(str(user["id"]))
    return {"status": "cleared", "deleted_count": deleted_count}


# ==============================================================================
# Provider Endpoints (Low-Level / Diagnostic)
# ==============================================================================

def _validate_russian_language_params(lang: Optional[str], language: Optional[str]) -> None:
    """
    Validate language query parameters independently.
    If either parameter is provided, it must strictly be 'ru'.
    If both are provided, both must be 'ru'.
    Any other value raises HTTP 400 Bad Request.
    """
    for param_name, param_val in (("lang", lang), ("language", language)):
        if param_val is not None and param_val.strip().lower() != "ru":
            raise HTTPException(
                status_code=400,
                detail=f"Only Russian language ('ru') is supported in Onigiri. Parameter '{param_name}' must be 'ru'.",
            )


@router.get("/providers")
async def list_providers(registry: ProviderRegistry = Depends(get_registry)):
    """List all available external manga providers."""
    return {"providers": registry.list_providers()}


@router.get("/providers/{provider_id}/search", response_model=ProviderSearchResult)
async def search_provider(
    provider_id: str,
    q: str = Query(..., min_length=1, description="Search query string"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    lang: Optional[str] = Query(None, description="Translation language filter (must be 'ru' if provided)"),
    language: Optional[str] = Query(None, description="Translation language filter (must be 'ru' if provided)"),
    provider: BaseMangaProvider = Depends(get_provider),
):
    """Search manga across an external provider (strictly restricted to Russian translations)."""
    _validate_russian_language_params(lang, language)
    try:
        return await provider.search(query=q, page=page, limit=limit, languages=["ru"])
    except ProviderRateLimitError as exc:
        headers = {"Retry-After": str(int(exc.retry_after))} if exc.retry_after else None
        raise HTTPException(status_code=429, detail=str(exc), headers=headers) from exc
    except ProviderNetworkError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/providers/{provider_id}/manga/{provider_manga_id}", response_model=ProviderMangaItem)
async def get_manga_details(
    provider_id: str,
    provider_manga_id: str,
    provider: BaseMangaProvider = Depends(get_provider),
):
    """Get metadata for a specific manga from provider."""
    try:
        return await provider.get_manga_details(provider_manga_id=provider_manga_id)
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProviderRateLimitError as exc:
        headers = {"Retry-After": str(int(exc.retry_after))} if exc.retry_after else None
        raise HTTPException(status_code=429, detail=str(exc), headers=headers) from exc
    except ProviderNetworkError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/providers/{provider_id}/manga/{provider_manga_id}/chapters",
    response_model=ProviderChaptersResult,
)
async def get_manga_chapters(
    provider_id: str,
    provider_manga_id: str,
    lang: Optional[str] = Query(None, description="Translation language filter (must be 'ru' if provided)"),
    language: Optional[str] = Query(None, description="Translation language filter (must be 'ru' if provided)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(100, ge=1, le=100, description="Items per page"),
    provider: BaseMangaProvider = Depends(get_provider),
):
    """Get paginated chapter feed for a manga (strictly Russian translations only)."""
    _validate_russian_language_params(lang, language)
    try:
        return await provider.get_chapters(
            provider_manga_id=provider_manga_id,
            language="ru",
            page=page,
            limit=limit,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProviderRateLimitError as exc:
        headers = {"Retry-After": str(int(exc.retry_after))} if exc.retry_after else None
        raise HTTPException(status_code=429, detail=str(exc), headers=headers) from exc
    except ProviderNetworkError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/providers/{provider_id}/chapters/{provider_chapter_id}/pages",
    response_model=ProviderPagesResult,
)
async def get_chapter_pages(
    provider_id: str,
    provider_chapter_id: str,
    data_saver: bool = Query(False, description="Use dataSaver compressed images"),
    provider: BaseMangaProvider = Depends(get_provider),
):
    """Get page image URLs for reading a chapter."""
    try:
        return await provider.get_chapter_pages(
            provider_chapter_id=provider_chapter_id,
            data_saver=data_saver,
        )
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProviderRateLimitError as exc:
        headers = {"Retry-After": str(int(exc.retry_after))} if exc.retry_after else None
        raise HTTPException(status_code=429, detail=str(exc), headers=headers) from exc
    except ProviderNetworkError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
