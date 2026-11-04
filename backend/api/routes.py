"""
API routes for Onigiri backend.
Includes health check, unified manga catalog endpoints, and provider inspection endpoints.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Generator, List, Optional

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
from schemas.manga import MangaDetailRead, MangaListRead
from services.catalog import CatalogService

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
# Unified Catalog Endpoints (Onigiri User-Facing API)
# ==============================================================================

@router.get("/manga/search", response_model=List[MangaListRead])
async def search_manga(
    q: str = Query(..., min_length=1, description="Search query string"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    catalog_service: CatalogService = Depends(get_catalog_service),
):
    """
    Search manga across the unified Onigiri catalog.
    Queries external Russian-translated sources (MangaDex) and local catalog.
    Returns unified Onigiri manga cards without exposing provider names.
    """
    return await catalog_service.search(query=q, page=page, limit=limit)


@router.get("/manga/cover/proxy")
async def get_manga_cover(
    url: str = Query(..., description="External cover image URL"),
):
    """
    Safely proxy external manga covers to bypass MangaDex anti-hotlinking bot-challenge (HTTP 403).
    Restricted strictly to authorized MangaDex CDN hosts.
    """
    clean_url = url.strip()
    if not clean_url.startswith("https://uploads.mangadex.org/"):
        raise HTTPException(status_code=400, detail="Invalid cover URL: host not permitted")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(clean_url, headers={"User-Agent": "Onigiri-App/1.0"})
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Failed to load cover from remote host")

            content_type = resp.headers.get("content-type", "image/jpeg")
            return Response(
                content=resp.content,
                media_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=604800, immutable",
                },
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Remote network error: {exc}")


@router.get("/manga/{id_or_slug}", response_model=MangaDetailRead)
async def get_manga_detail(
    id_or_slug: str,
    catalog_service: CatalogService = Depends(get_catalog_service),
):
    """
    Get full manga details by Onigiri ID or slug.
    Returns unified manga card. External sources are sanitized/omitted.
    """
    manga = await catalog_service.get_manga_by_id_or_slug(id_or_slug)
    if not manga:
        raise HTTPException(status_code=404, detail="Manga not found")
    return manga


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
