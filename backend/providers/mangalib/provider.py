"""
MangaLib Provider implementation for Onigiri.
Coordinates title search, metadata retrieval, chapter indexing, and page URLs.
Reserve manga source for Onigiri.
"""

from datetime import datetime
import logging
from typing import Any, Dict, List, Optional

from providers.base import (
    BaseMangaProvider,
    ProviderChapterItem,
    ProviderChaptersResult,
    ProviderMangaItem,
    ProviderPageItem,
    ProviderPagesResult,
    ProviderSearchResult,
)
from providers.mangalib.client import MangaLibHttpClient

logger = logging.getLogger(__name__)

PRIMARY_IMG_SERVER = "https://img3.cdnrulib.link"


class MangaLibProvider(BaseMangaProvider):
    """
    MangaLib provider implementation.
    Reserve manga source for Onigiri.
    """

    def __init__(self, client: Optional[MangaLibHttpClient] = None) -> None:
        self.client = client or MangaLibHttpClient()

    @property
    def provider_id(self) -> str:
        return "mangalib"

    @property
    def name(self) -> str:
        return "MangaLib"

    async def search(
        self,
        query: str,
        page: int = 1,
        limit: int = 20,
        languages: Optional[List[str]] = None,
    ) -> ProviderSearchResult:
        """Search manga on MangaLib."""
        clean_query = query.strip()
        if not clean_query:
            return ProviderSearchResult(
                provider_id=self.provider_id,
                items=[],
                total=0,
                page=page,
                limit=limit,
                has_next=False,
            )

        api_limit = max(10, min(limit, 60))
        params: Dict[str, Any] = {
            "q": clean_query,
            "site_id[]": 1,  # 1 = MangaLib
            "page": page,
            "limit": api_limit,
        }

        data = await self.client.request("GET", "/api/manga", params=params)
        results = data.get("data", [])
        meta = data.get("meta", {})
        has_next_page = meta.get("has_next_page", False)

        items: List[ProviderMangaItem] = []
        for it in results:
            slug_url = it.get("slug_url")
            if not slug_url:
                continue

            rus_name = (it.get("rus_name") or "").strip()
            orig_name = (it.get("name") or "").strip()
            title = rus_name or orig_name or slug_url

            alt_titles: List[str] = []
            if orig_name and orig_name != title:
                alt_titles.append(orig_name)
            if rus_name and rus_name != title and rus_name not in alt_titles:
                alt_titles.append(rus_name)

            cover_obj = it.get("cover", {})
            cover_url = None
            if isinstance(cover_obj, dict):
                cover_url = cover_obj.get("default") or cover_obj.get("thumbnail")

            status_obj = it.get("status")
            status_str = "ongoing"
            if isinstance(status_obj, dict):
                st_label = status_obj.get("label", "").lower()
                if "заверш" in st_label:
                    status_str = "completed"
                elif "приостанов" in st_label or "заморож" in st_label:
                    status_str = "hiatus"

            release_date = it.get("release_date")
            year = None
            if release_date and isinstance(release_date, str):
                try:
                    year = int(release_date[:4])
                except Exception:
                    pass

            items.append(
                ProviderMangaItem(
                    provider_id=self.provider_id,
                    provider_manga_id=slug_url,
                    title=title,
                    alt_titles=alt_titles,
                    description=it.get("summary"),
                    cover_url=cover_url,
                    status=status_str,
                    release_year=year,
                    available_languages=["ru"],
                    source_url=f"https://mangalib.me/ru/{slug_url}",
                )
            )

        return ProviderSearchResult(
            provider_id=self.provider_id,
            items=items,
            total=len(items),
            page=page,
            limit=limit,
            has_next=has_next_page,
        )

    async def get_manga_details(self, provider_manga_id: str) -> ProviderMangaItem:
        """Retrieve details for manga by searching its slug_url."""
        import re
        clean_q = re.sub(r'^\d+--', '', provider_manga_id).replace('-', ' ').replace('_', ' ').strip()
        params: Dict[str, Any] = {
            "q": clean_q or provider_manga_id,
            "site_id[]": 1,
            "limit": 10,
        }
        data = await self.client.request("GET", "/api/manga", params=params)
        results = data.get("data", [])

        # Find exact match on slug_url
        matched_item = None
        for it in results:
            if it.get("slug_url") == provider_manga_id:
                matched_item = it
                break

        if not matched_item and results:
            matched_item = results[0]

        if not matched_item:
            matched_item = {
                "slug_url": provider_manga_id,
                "name": clean_q.title(),
                "rus_name": clean_q.title(),
            }

        rus_name = (matched_item.get("rus_name") or "").strip()
        orig_name = (matched_item.get("name") or "").strip()
        title = rus_name or orig_name or provider_manga_id

        alt_titles: List[str] = []
        if orig_name and orig_name != title:
            alt_titles.append(orig_name)
        if rus_name and rus_name != title and rus_name not in alt_titles:
            alt_titles.append(rus_name)

        cover_obj = matched_item.get("cover", {})
        cover_url = None
        if isinstance(cover_obj, dict):
            cover_url = cover_obj.get("default") or cover_obj.get("thumbnail")

        status_obj = matched_item.get("status")
        status_str = "ongoing"
        if isinstance(status_obj, dict):
            st_label = status_obj.get("label", "").lower()
            if "заверш" in st_label:
                status_str = "completed"
            elif "приостанов" in st_label or "заморож" in st_label:
                status_str = "hiatus"

        release_date = matched_item.get("release_date")
        year = None
        if release_date and isinstance(release_date, str):
            try:
                year = int(release_date[:4])
            except Exception:
                pass

        return ProviderMangaItem(
            provider_id=self.provider_id,
            provider_manga_id=provider_manga_id,
            title=title,
            alt_titles=alt_titles,
            description=matched_item.get("summary"),
            cover_url=cover_url,
            status=status_str,
            release_year=year,
            available_languages=["ru"],
            source_url=f"https://mangalib.me/ru/{provider_manga_id}",
        )

    async def get_chapters(
        self,
        provider_manga_id: str,
        language: str = "ru",
        page: int = 1,
        limit: int = 100,
    ) -> ProviderChaptersResult:
        """Fetch all chapters for a manga on MangaLib."""
        data = await self.client.request("GET", f"/api/manga/{provider_manga_id}/chapters")
        results = data.get("data", [])

        # MangaLib returns all chapters in a single call, or order by volume/number
        chapters: List[ProviderChapterItem] = []
        for ch in results:
            raw_num = str(ch.get("number", "0"))
            try:
                num_val = float(raw_num)
            except ValueError:
                num_val = 0.0

            vol = ch.get("volume", "1")
            try:
                vol_val = int(vol)
            except (ValueError, TypeError):
                vol_val = 1

            cid = f"{provider_manga_id}:{vol_val}:{raw_num}"

            branches = ch.get("branches", [])
            scan_group = None
            if branches and isinstance(branches[0], dict):
                teams = branches[0].get("teams", [])
                if teams and isinstance(teams[0], dict):
                    scan_group = teams[0].get("name")

            created_str = ch.get("created_at")
            dt = None
            if created_str:
                try:
                    dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                except Exception:
                    pass

            chapters.append(
                ProviderChapterItem(
                    provider_id=self.provider_id,
                    provider_manga_id=provider_manga_id,
                    provider_chapter_id=cid,
                    chapter_number_raw=raw_num,
                    chapter_number_numeric=num_val,
                    volume_number=vol_val,
                    title=ch.get("name") or None,
                    language="ru",
                    scanlation_group=scan_group,
                    published_at=dt,
                )
            )

        # Sort ascending by volume then chapter number
        chapters.sort(key=lambda c: (c.volume_number or 0, c.chapter_number_numeric or 0.0))

        # Paginate in memory if limit requested
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        page_chapters = chapters[start_idx:end_idx]
        has_next = end_idx < len(chapters)

        return ProviderChaptersResult(
            provider_id=self.provider_id,
            provider_manga_id=provider_manga_id,
            chapters=page_chapters,
            total=len(chapters),
            page=page,
            limit=limit,
            has_next=has_next,
        )

    async def get_chapter_pages(
        self,
        provider_chapter_id: str,
        data_saver: bool = False,
    ) -> ProviderPagesResult:
        """
        Retrieve page image URLs for reading a chapter.
        provider_chapter_id format: "{slug_url}:{volume}:{number}"
        """
        parts = provider_chapter_id.split(":")
        if len(parts) >= 3:
            slug_url, vol, num = parts[0], parts[1], parts[2]
        else:
            raise ValueError(f"Invalid MangaLib chapter ID format: {provider_chapter_id}")

        params = {"volume": vol, "number": num}
        data = await self.client.request("GET", f"/api/manga/{slug_url}/chapter", params=params)
        chapter_data = data.get("data", data)
        raw_pages = chapter_data.get("pages", [])

        pages: List[ProviderPageItem] = []
        for idx, p in enumerate(raw_pages, start=1):
            rel_url = p.get("url", "")
            clean_rel = rel_url.lstrip("/")
            full_img_url = f"{PRIMARY_IMG_SERVER}/{clean_rel}"
            pages.append(
                ProviderPageItem(
                    page_number=idx,
                    image_url=full_img_url,
                )
            )

        return ProviderPagesResult(
            provider_id=self.provider_id,
            provider_chapter_id=provider_chapter_id,
            pages=pages,
            data_saver=data_saver,
            expires_at=None,
        )

    async def close(self) -> None:
        """Close persistent HTTP session."""
        await self.client.close()
