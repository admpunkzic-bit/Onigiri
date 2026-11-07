"""
ReManga Provider implementation for Onigiri.
Coordinates title search, metadata retrieval, chapter indexing, and page URLs.
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
from providers.remanga.client import ReMangaHttpClient, MEDIA_BASE_URL

logger = logging.getLogger(__name__)


def _build_cover_url(img_data: Any) -> Optional[str]:
    """Build full cover image URL from ReManga cover/img object or string."""
    if not img_data:
        return None
    if isinstance(img_data, str):
        clean = img_data.strip()
        if clean.startswith("http"):
            return clean
        clean = clean.lstrip("/")
        return f"{MEDIA_BASE_URL}/{clean}"
    if isinstance(img_data, dict):
        rel_path = img_data.get("high") or img_data.get("mid") or img_data.get("low")
        if rel_path and isinstance(rel_path, str):
            clean = rel_path.strip().lstrip("/")
            return f"{MEDIA_BASE_URL}/{clean}"
    return None


class ReMangaProvider(BaseMangaProvider):
    """
    ReManga provider implementation.
    Primary manga source for Onigiri.
    """

    def __init__(self, client: Optional[ReMangaHttpClient] = None) -> None:
        self.client = client or ReMangaHttpClient()

    @property
    def provider_id(self) -> str:
        return "remanga"

    @property
    def name(self) -> str:
        return "ReManga"

    async def search(
        self,
        query: str,
        page: int = 1,
        limit: int = 20,
        languages: Optional[List[str]] = None,
    ) -> ProviderSearchResult:
        """Search titles on ReManga."""
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

        params: Dict[str, Any] = {
            "query": clean_query,
            "page": page,
            "count": limit,
        }

        data = await self.client.request("GET", "/api/v2/search/", params=params)
        results = data.get("results", [])
        meta = data.get("meta", {})
        total_items = meta.get("total_items", len(results))
        total_pages = meta.get("total_pages", 1)

        items: List[ProviderMangaItem] = []
        for r in results:
            dir_slug = r.get("dir")
            if not dir_slug:
                continue

            main_name = (r.get("main_name") or "").strip()
            sec_name = (r.get("secondary_name") or "").strip()
            title = main_name or sec_name
            if not title:
                continue

            alt_titles = []
            if sec_name and sec_name != main_name:
                alt_titles.append(sec_name)
            if main_name and main_name != title:
                alt_titles.append(main_name)

            cover_url = _build_cover_url(r.get("cover") or r.get("img"))
            status_obj = r.get("status")
            status_str = "ongoing"
            if isinstance(status_obj, dict):
                st_name = status_obj.get("name", "").lower()
                if "закончен" in st_name:
                    status_str = "completed"
                elif "заморожен" in st_name:
                    status_str = "hiatus"
                elif "приостановлен" in st_name:
                    status_str = "hiatus"

            issue_year = r.get("issue_year")

            items.append(
                ProviderMangaItem(
                    provider_id=self.provider_id,
                    provider_manga_id=dir_slug,
                    title=title,
                    alt_titles=alt_titles,
                    description=r.get("description"),
                    cover_url=cover_url,
                    status=status_str,
                    release_year=issue_year if isinstance(issue_year, int) else None,
                    available_languages=["ru"],
                    source_url=f"https://remanga.org/manga/{dir_slug}",
                )
            )

        return ProviderSearchResult(
            provider_id=self.provider_id,
            items=items,
            total=total_items,
            page=page,
            limit=limit,
            has_next=page < total_pages,
        )

    async def get_manga_details(self, provider_manga_id: str) -> ProviderMangaItem:
        """Retrieve full details for a manga by its dir slug."""
        data = await self.client.request("GET", f"/api/v2/titles/{provider_manga_id}/")
        content = data.get("content", data)

        main_name = (content.get("main_name") or "").strip()
        sec_name = (content.get("secondary_name") or "").strip()
        title = main_name or sec_name or provider_manga_id

        alt_titles = []
        if sec_name and sec_name != title:
            alt_titles.append(sec_name)
        another_name = content.get("another_name")
        if another_name and isinstance(another_name, str):
            for a in another_name.split(","):
                clean_a = a.strip()
                if clean_a and clean_a not in alt_titles:
                    alt_titles.append(clean_a)

        cover_url = _build_cover_url(content.get("cover") or content.get("img"))
        status_obj = content.get("status")
        status_str = "ongoing"
        if isinstance(status_obj, dict):
            st_name = status_obj.get("name", "").lower()
            if "закончен" in st_name:
                status_str = "completed"
            elif "заморожен" in st_name or "приостановлен" in st_name:
                status_str = "hiatus"

        genres = [g.get("name") for g in content.get("genres", []) if isinstance(g, dict) and g.get("name")]
        categories = [c.get("name") for c in content.get("categories", []) if isinstance(c, dict) and c.get("name")]
        all_tags = list(dict.fromkeys(genres + categories))

        authors = [cr.get("name") for cr in content.get("creators", []) if isinstance(cr, dict) and cr.get("name")]

        return ProviderMangaItem(
            provider_id=self.provider_id,
            provider_manga_id=provider_manga_id,
            title=title,
            alt_titles=alt_titles,
            description=content.get("description"),
            cover_url=cover_url,
            status=status_str,
            release_year=content.get("issue_year"),
            authors=authors,
            genres=all_tags,
            available_languages=["ru"],
            source_url=f"https://remanga.org/manga/{provider_manga_id}",
        )

    async def get_chapters(
        self,
        provider_manga_id: str,
        language: str = "ru",
        page: int = 1,
        limit: int = 100,
    ) -> ProviderChaptersResult:
        """
        Fetch paginated chapter feed for manga in ascending chapter order.
        Resolves active branch from title details if not specified.
        """
        title_data = await self.client.request("GET", f"/api/v2/titles/{provider_manga_id}/")
        branches = title_data.get("branches", [])
        if not branches:
            return ProviderChaptersResult(
                provider_id=self.provider_id,
                provider_manga_id=provider_manga_id,
                chapters=[],
                total=0,
                page=page,
                limit=limit,
                has_next=False,
            )

        # Select primary branch (largest chapter count or active)
        active_branch = branches[0]
        max_ch_count = active_branch.get("count_chapters", 0)
        for b in branches:
            if b.get("count_chapters", 0) > max_ch_count:
                active_branch = b
                max_ch_count = b.get("count_chapters", 0)

        branch_id = active_branch["id"]
        publishers = active_branch.get("publishers", [])
        scan_group = publishers[0].get("name") if publishers else None

        params = {
            "branch_id": branch_id,
            "count": limit,
            "page": page,
            "ordering": "index",  # Ascending volume/chapter order
        }

        ch_data = await self.client.request("GET", "/api/v2/titles/chapters/", params=params)
        results = ch_data.get("results", [])
        has_next = bool(ch_data.get("next"))

        chapters: List[ProviderChapterItem] = []
        for ch in results:
            cid = str(ch.get("id"))
            raw_ch = str(ch.get("chapter", "0"))
            try:
                num_val = float(raw_ch)
            except ValueError:
                num_val = 0.0

            tome = ch.get("tome")
            vol_val = int(tome) if tome is not None else None

            pub_date_str = ch.get("pub_date") or ch.get("upload_date")
            dt = None
            if pub_date_str:
                try:
                    dt = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                except Exception:
                    pass

            chapters.append(
                ProviderChapterItem(
                    provider_id=self.provider_id,
                    provider_manga_id=provider_manga_id,
                    provider_chapter_id=cid,
                    chapter_number_raw=raw_ch,
                    chapter_number_numeric=num_val,
                    volume_number=vol_val,
                    title=ch.get("name") or None,
                    language="ru",
                    scanlation_group=scan_group,
                    published_at=dt,
                )
            )

        return ProviderChaptersResult(
            provider_id=self.provider_id,
            provider_manga_id=provider_manga_id,
            chapters=chapters,
            total=max_ch_count or len(chapters),
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
        ReManga provides direct full-resolution image links in pages list.
        """
        data = await self.client.request("GET", f"/api/v2/titles/chapters/{provider_chapter_id}/")
        raw_pages = data.get("pages", [])

        # ReManga returns a list of page lists or list of dicts: [[{id: 1, link: ...}, ...]]
        flat_pages: List[Dict[str, Any]] = []
        if raw_pages and isinstance(raw_pages[0], list):
            flat_pages = raw_pages[0]
        elif raw_pages and isinstance(raw_pages[0], dict):
            flat_pages = raw_pages

        pages: List[ProviderPageItem] = []
        for idx, p in enumerate(flat_pages, start=1):
            link = p.get("link")
            if link:
                pages.append(
                    ProviderPageItem(
                        page_number=idx,
                        image_url=link,
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
