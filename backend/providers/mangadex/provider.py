"""
MangaDex provider implementation of BaseMangaProvider.
"""

from datetime import datetime
import logging
from typing import Any, Dict, List, Optional, Tuple

from providers.base import (
    BaseMangaProvider,
    ProviderChapterItem,
    ProviderChaptersResult,
    ProviderMangaItem,
    ProviderPageItem,
    ProviderPagesResult,
    ProviderSearchResult,
)
from providers.mangadex.client import MangaDexHttpClient

logger = logging.getLogger(__name__)

MANGADEX_COVER_BASE_URL = "https://uploads.mangadex.org/covers"


class MangaDexProvider(BaseMangaProvider):
    """
    Adapter implementing BaseMangaProvider for the official MangaDex REST API.
    """

    def __init__(self, client: Optional[MangaDexHttpClient] = None):
        self._client = client or MangaDexHttpClient()

    @property
    def provider_id(self) -> str:
        return "mangadex"

    @property
    def name(self) -> str:
        return "MangaDex"

    # ==========================================================================
    # Helpers for parsing MangaDex API structures
    # ==========================================================================

    @staticmethod
    def _parse_title(attributes: Dict[str, Any]) -> str:
        """Extract primary title from attributes.title dictionary."""
        titles_dict = attributes.get("title") or {}
        # Try preferred languages in order: en, ru, ja-ro, or first available
        for lang in ("en", "ru", "ja-ro"):
            if lang in titles_dict:
                return titles_dict[lang]
        if titles_dict:
            return next(iter(titles_dict.values()))
        return "Untitled"

    @staticmethod
    def _parse_alt_titles(attributes: Dict[str, Any]) -> List[str]:
        """Extract all alternative titles."""
        alt_list = attributes.get("altTitles") or []
        results = []
        for item in alt_list:
            if isinstance(item, dict):
                results.extend(item.values())
        return results

    @staticmethod
    def _parse_description(attributes: Dict[str, Any]) -> Optional[str]:
        """Extract description, preferring Russian, then English."""
        desc_dict = attributes.get("description") or {}
        if isinstance(desc_dict, str):
            return desc_dict
        if "ru" in desc_dict and desc_dict["ru"].strip():
            return desc_dict["ru"]
        if "en" in desc_dict and desc_dict["en"].strip():
            return desc_dict["en"]
        if desc_dict:
            return next(iter(desc_dict.values()))
        return None

    @staticmethod
    def _parse_cover_url(manga_id: str, relationships: List[Dict[str, Any]]) -> Optional[str]:
        """Extract cover image URL from cover_art relationship."""
        for rel in relationships:
            if rel.get("type") == "cover_art":
                attrs = rel.get("attributes") or {}
                file_name = attrs.get("fileName")
                if file_name:
                    # Request 512px optimized thumbnail for mobile efficiency
                    return f"{MANGADEX_COVER_BASE_URL}/{manga_id}/{file_name}.512.jpg"
        return None

    @staticmethod
    def _parse_authors_and_artists(relationships: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
        """Extract author and artist names from relationships."""
        authors = []
        artists = []
        for rel in relationships:
            rel_type = rel.get("type")
            attrs = rel.get("attributes") or {}
            name = attrs.get("name")
            if not name:
                continue
            if rel_type == "author":
                authors.append(name)
            elif rel_type == "artist":
                artists.append(name)
        return authors, artists

    @staticmethod
    def _parse_genres(attributes: Dict[str, Any]) -> List[str]:
        """Extract genres / tags from attributes.tags."""
        tags = attributes.get("tags") or []
        genres = []
        for tag in tags:
            tag_attrs = tag.get("attributes") or {}
            name_dict = tag_attrs.get("name") or {}
            genre_name = name_dict.get("en") or next(iter(name_dict.values()), None)
            if genre_name:
                genres.append(genre_name)
        return genres

    def _build_manga_item(self, data: Dict[str, Any]) -> ProviderMangaItem:
        """Convert a MangaDex manga data object into ProviderMangaItem."""
        manga_id = data["id"]
        attrs = data.get("attributes") or {}
        rels = data.get("relationships") or []

        authors, artists = self._parse_authors_and_artists(rels)
        genres = self._parse_genres(attrs)
        cover_url = self._parse_cover_url(manga_id, rels)

        return ProviderMangaItem(
            provider_id=self.provider_id,
            provider_manga_id=manga_id,
            title=self._parse_title(attrs),
            alt_titles=self._parse_alt_titles(attrs),
            description=self._parse_description(attrs),
            cover_url=cover_url,
            status=attrs.get("status") or "unknown",
            release_year=attrs.get("year"),
            authors=authors,
            artists=artists,
            genres=genres,
            available_languages=attrs.get("availableTranslatedLanguages") or [],
            source_url=f"https://mangadex.org/title/{manga_id}",
        )

    # ==========================================================================
    # Public Provider Methods
    # ==========================================================================

    async def search(
        self,
        query: str,
        page: int = 1,
        limit: int = 20,
        languages: Optional[List[str]] = None,
    ) -> ProviderSearchResult:
        """Search manga on MangaDex with pagination."""
        safe_page = max(1, page)
        safe_limit = max(1, min(100, limit))
        offset = (safe_page - 1) * safe_limit

        raw = await self._client.search_manga(
            title=query,
            limit=safe_limit,
            offset=offset,
            languages=languages,
        )

        data_list = raw.get("data") or []
        total = int(raw.get("total", len(data_list)))
        items = [self._build_manga_item(item) for item in data_list]
        has_next = (offset + safe_limit) < total

        return ProviderSearchResult(
            provider_id=self.provider_id,
            items=items,
            total=total,
            page=safe_page,
            limit=safe_limit,
            has_next=has_next,
        )

    async def get_manga_details(self, provider_manga_id: str) -> ProviderMangaItem:
        """Fetch details for a single manga."""
        raw = await self._client.get_manga(provider_manga_id)
        return self._build_manga_item(raw["data"])

    async def get_chapters(
        self,
        provider_manga_id: str,
        language: str = "ru",
        page: int = 1,
        limit: int = 100,
    ) -> ProviderChaptersResult:
        """
        Fetch paginated chapter feed for a manga in requested language.
        Preserves raw numbering and accurately calculates numeric chapter values.
        """
        safe_page = max(1, page)
        safe_limit = max(1, min(100, limit))
        offset = (safe_page - 1) * safe_limit

        raw = await self._client.get_manga_feed(
            manga_id=provider_manga_id,
            limit=safe_limit,
            offset=offset,
            language=language,
        )

        chapter_entries = raw.get("data") or []
        total = int(raw.get("total", len(chapter_entries)))
        chapters: List[ProviderChapterItem] = []

        for ch in chapter_entries:
            ch_id = ch["id"]
            attrs = ch.get("attributes") or {}
            rels = ch.get("relationships") or []

            raw_num: Optional[str] = attrs.get("chapter")
            numeric_num: Optional[float] = None
            is_special = False

            if raw_num is not None and raw_num.strip():
                try:
                    numeric_num = float(raw_num)
                except ValueError:
                    numeric_num = None
                    is_special = True
            else:
                raw_num = None
                numeric_num = None
                is_special = True

            # Volume number parsing
            vol_raw = attrs.get("volume")
            volume_num: Optional[int] = None
            if vol_raw is not None:
                try:
                    volume_num = int(vol_raw)
                except (ValueError, TypeError):
                    volume_num = None

            # Scanlation group
            scanlation_group = None
            for rel in rels:
                if rel.get("type") == "scanlation_group":
                    group_attrs = rel.get("attributes") or {}
                    scanlation_group = group_attrs.get("name")
                    if scanlation_group:
                        break

            # Publish date
            published_at = None
            pub_str = attrs.get("publishAt") or attrs.get("readableAt")
            if pub_str:
                try:
                    published_at = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                except ValueError:
                    published_at = None

            chapters.append(
                ProviderChapterItem(
                    provider_id=self.provider_id,
                    provider_manga_id=provider_manga_id,
                    provider_chapter_id=ch_id,
                    chapter_number_raw=raw_num,
                    chapter_number_numeric=numeric_num,
                    is_special=is_special,
                    volume_number=volume_num,
                    title=attrs.get("title"),
                    language=attrs.get("translatedLanguage", language),
                    scanlation_group=scanlation_group,
                    published_at=published_at,
                )
            )

        has_next = (offset + safe_limit) < total

        return ProviderChaptersResult(
            provider_id=self.provider_id,
            provider_manga_id=provider_manga_id,
            chapters=chapters,
            total=total,
            page=safe_page,
            limit=safe_limit,
            has_next=has_next,
        )

    async def get_chapter_pages(
        self,
        provider_chapter_id: str,
        data_saver: bool = False,
    ) -> ProviderPagesResult:
        """
        Fetch page image URLs for a chapter using MangaDex@Home.
        Does not invent expiration timestamps: expires_at is None.
        """
        raw = await self._client.get_at_home_server(provider_chapter_id)

        base_url = raw.get("baseUrl")
        ch_dict = raw.get("chapter") or {}
        ch_hash = ch_dict.get("hash")

        files: List[str] = ch_dict.get("dataSaver" if data_saver else "data") or []
        folder = "data-saver" if data_saver else "data"

        pages: List[ProviderPageItem] = []
        for idx, file_name in enumerate(files, start=1):
            page_url = f"{base_url}/{folder}/{ch_hash}/{file_name}"
            pages.append(ProviderPageItem(page_number=idx, image_url=page_url))

        return ProviderPagesResult(
            provider_id=self.provider_id,
            provider_chapter_id=provider_chapter_id,
            pages=pages,
            data_saver=data_saver,
            expires_at=None,  # Do not invent expiration date
        )

    async def close(self) -> None:
        """Close underlying client."""
        await self._client.close()
