"""
Manga-Chan provider implementation of BaseMangaProvider.
"""

from datetime import datetime
import html
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from providers.base import (
    BaseMangaProvider,
    ProviderChapterItem,
    ProviderChaptersResult,
    ProviderMangaItem,
    ProviderNotFoundError,
    ProviderPageItem,
    ProviderPagesResult,
    ProviderSearchResult,
)
from providers.mangachan.client import MangaChanHttpClient

logger = logging.getLogger(__name__)


class MangaChanProvider(BaseMangaProvider):
    """
    Adapter implementing BaseMangaProvider for Manga-Chan (im.manga-chan.me).
    """

    def __init__(self, client: Optional[MangaChanHttpClient] = None):
        self._client = client or MangaChanHttpClient()

    @property
    def provider_id(self) -> str:
        return "mangachan"

    @property
    def name(self) -> str:
        return "Manga-Chan"

    @property
    def supported_languages(self) -> List[str]:
        return ["ru"]

    # ==========================================================================
    # Helpers for parsing Manga-Chan HTML
    # ==========================================================================

    @staticmethod
    def _clean_text(raw: str) -> str:
        clean = html.unescape(raw)
        clean = re.sub(r"<[^>]+>", " ", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    @classmethod
    def _parse_search_html(cls, html_content: str) -> List[ProviderMangaItem]:
        results: List[ProviderMangaItem] = []
        seen_ids = set()

        # DLE search cards: matches /manga/(\d+-[^"]+\.html)
        pattern = re.compile(
            r'<a[^>]+href=[\'"](?:https?://[^\'"]+)?/manga/(\d+-[^\'"\s]+?\.html)[\'"][^>]*>([^<]+)</a>',
            re.IGNORECASE,
        )

        for match in pattern.finditer(html_content):
            slug = match.group(1).replace(".html", "").strip()
            raw_title = cls._clean_text(match.group(2))
            if not slug or slug in seen_ids or not raw_title:
                continue

            # Skip header or nav links
            if raw_title.lower() in ("каталог манги", "манга онлайн", "главная"):
                continue

            seen_ids.add(slug)

            # Extract alt title if in parentheses: "The gamer (Игрок)"
            title = raw_title
            alt_titles: List[str] = []
            alt_match = re.search(r"^(.*?)\s*\((.*?)\)$", raw_title)
            if alt_match:
                title = alt_match.group(1).strip()
                alt_titles.append(alt_match.group(2).strip())

            # Attempt to find adjacent cover image
            cover_url = None
            pos = match.start()
            # Look in the surrounding snippet (500 chars before and 200 chars after)
            img_snippet = html_content[max(0, pos - 500) : min(len(html_content), pos + 200)]
            img_match = re.search(r'<img[^>]+src=[\'"](https?://[^\'"]*(?:manga-chan|imgcover|thumbs)[^\'"]*)[\'"]', img_snippet)
            if img_match:
                cover_url = img_match.group(1)
                if cover_url.startswith("http://"):
                    cover_url = "https://" + cover_url[7:]

            results.append(
                ProviderMangaItem(
                    provider_id="mangachan",
                    provider_manga_id=slug,
                    title=title,
                    alt_titles=alt_titles,
                    description=None,
                    cover_url=cover_url,
                    status="ongoing",
                    release_year=None,
                    authors=[],
                    artists=[],
                    genres=[],
                    available_languages=["ru"],
                    source_url=f"https://im.manga-chan.me/manga/{slug}.html",
                )
            )

        return results

    @classmethod
    def _parse_manga_details(cls, slug: str, html_content: str) -> ProviderMangaItem:
        # Title extraction from <h1> or .manga_title
        title = slug
        alt_titles: List[str] = []
        h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html_content, re.IGNORECASE | re.DOTALL)
        if h1_match:
            raw_h1 = cls._clean_text(h1_match.group(1))
            alt_match = re.search(r"^(.*?)\s*\((.*?)\)$", raw_h1)
            if alt_match:
                title = alt_match.group(1).strip()
                alt_titles.append(alt_match.group(2).strip())
            else:
                title = raw_h1

        # Description
        desc = None
        desc_match = re.search(
            r'id="description"[^>]*>(.*?)</div>', html_content, re.IGNORECASE | re.DOTALL
        )
        if desc_match:
            desc = cls._clean_text(desc_match.group(1))

        # Cover
        cover_url = None
        cover_match = re.search(
            r'<img[^>]+id=[\'"]cover[\'"][^>]+src=[\'"](https?://[^\'"]+)[\'"]',
            html_content,
            re.IGNORECASE,
        )
        if cover_match:
            cover_url = cover_match.group(1)
        else:
            # Fallback search for any imgcover image
            alt_cover = re.search(r'src=[\'"](https?://imgcover\.[^\'"]+)[\'"]', html_content)
            if alt_cover:
                cover_url = alt_cover.group(1)
        if cover_url and cover_url.startswith("http://"):
            cover_url = "https://" + cover_url[7:]

        # Status
        status = "ongoing"
        if "перевод: завершен" in html_content.lower():
            status = "completed"

        # Authors
        authors: List[str] = []
        author_match = re.search(
            r"Автор(?:ы)?:.*?<a[^>]+>([^<]+)</a>", html_content, re.IGNORECASE | re.DOTALL
        )
        if author_match:
            authors.append(cls._clean_text(author_match.group(1)))

        # Genres
        genres: List[str] = []
        genre_matches = re.findall(
            r'href=[\'"][^\'"]*tags/[^\'"]*[\'"][^>]*>([^<]+)</a>', html_content, re.IGNORECASE
        )
        for g in genre_matches:
            clean_g = cls._clean_text(g)
            if clean_g and clean_g not in genres:
                genres.append(clean_g)

        return ProviderMangaItem(
            provider_id="mangachan",
            provider_manga_id=slug,
            title=title,
            alt_titles=alt_titles,
            description=desc,
            cover_url=cover_url,
            status=status,
            release_year=None,
            authors=authors,
            artists=[],
            genres=genres,
            available_languages=["ru"],
            source_url=f"https://im.manga-chan.me/manga/{slug}.html",
        )

    @classmethod
    def _parse_chapters_from_html(cls, slug: str, html_content: str) -> List[ProviderChapterItem]:
        chapters: List[ProviderChapterItem] = []
        seen_ch_ids = set()

        # Matches: <a href='.../online/(ID).html' ...>Title</a> ... <div class='date'>Date</div>
        # Also supports relative /online/(ID).html
        ch_regex = re.compile(
            r"<a[^>]+href=[\'\"'](?:https?://[^\'\"']+)?/online/(\d+-[^\'\"'\s]+?\.html)[\'\"'][^>]*>(.*?)</a>.*?(?:<div class=[\'\"']date[\'\"']>([^<]*)</div>)?",
            re.IGNORECASE | re.DOTALL,
        )

        for match in ch_regex.finditer(html_content):
            ch_file = match.group(1)
            raw_title = cls._clean_text(match.group(2))
            date_str = match.group(3).strip() if match.group(3) else None

            ch_id = ch_file.replace(".html", "").strip()
            if not ch_id or ch_id in seen_ch_ids:
                continue

            # Ignore cover thumbnail link to first chapter if title is empty
            if not raw_title or "<img" in match.group(2):
                continue

            seen_ch_ids.add(ch_id)

            # Volume and chapter extraction from title e.g. "Том 7  Глава 44"
            volume_num: Optional[int] = None
            vol_match = re.search(r"Том\s+(\d+)", raw_title, re.IGNORECASE)
            if vol_match:
                try:
                    volume_num = int(vol_match.group(1))
                except ValueError:
                    pass

            ch_num_numeric: Optional[float] = None
            ch_num_raw: Optional[str] = None
            is_special = False

            ch_match = re.search(r"Глава\s+(\d+(?:\.\d+)?)", raw_title, re.IGNORECASE)
            if ch_match:
                ch_num_raw = ch_match.group(1)
                try:
                    ch_num_numeric = float(ch_num_raw)
                except ValueError:
                    ch_num_numeric = None
            else:
                # Check for prologue, extra, special
                if any(k in raw_title.lower() for k in ("экстра", "пролог", "спец", "extra", "prologue")):
                    is_special = True
                else:
                    # Generic number fallback
                    num_match = re.search(r"(\d+(?:\.\d+)?)", raw_title)
                    if num_match:
                        ch_num_raw = num_match.group(1)
                        try:
                            ch_num_numeric = float(ch_num_raw)
                        except ValueError:
                            pass

            published_at = None
            if date_str:
                try:
                    published_at = datetime.strptime(date_str, "%Y-%m-%d")
                except ValueError:
                    pass

            chapters.append(
                ProviderChapterItem(
                    provider_id="mangachan",
                    provider_manga_id=slug,
                    provider_chapter_id=ch_id,
                    chapter_number_raw=ch_num_raw,
                    chapter_number_numeric=ch_num_numeric,
                    is_special=is_special,
                    volume_number=volume_num,
                    title=raw_title,
                    language="ru",
                    scanlation_group=None,
                    published_at=published_at,
                )
            )

        # Manga-Chan lists chapters newest first (descending). Reverse to ascending standard order.
        chapters.sort(
            key=lambda c: (
                c.volume_number if c.volume_number is not None else 0,
                c.chapter_number_numeric if c.chapter_number_numeric is not None else 999999.0,
            )
        )
        return chapters

    # ==========================================================================
    # BaseMangaProvider Implementation
    # ==========================================================================

    async def search(
        self,
        query: str,
        page: int = 1,
        limit: int = 20,
        languages: Optional[List[str]] = None,
    ) -> ProviderSearchResult:
        clean_q = query.strip()
        if not clean_q:
            return ProviderSearchResult(
                provider_id="mangachan", items=[], total=0, page=page, limit=limit, has_next=False
            )

        html_content = await self._client.search(clean_q)
        items = self._parse_search_html(html_content)

        start = (page - 1) * limit
        paginated = items[start : start + limit]
        has_next = len(items) > (start + limit)

        return ProviderSearchResult(
            provider_id="mangachan",
            items=paginated,
            total=len(items),
            page=page,
            limit=limit,
            has_next=has_next,
        )

    async def get_manga_details(self, provider_manga_id: str) -> ProviderMangaItem:
        slug = provider_manga_id.strip()
        html_content = await self._client.get_manga(slug)
        return self._parse_manga_details(slug, html_content)

    async def get_chapters(
        self,
        provider_manga_id: str,
        language: str = "ru",
        page: int = 1,
        limit: int = 100,
    ) -> ProviderChaptersResult:
        if language != "ru":
            return ProviderChaptersResult(
                provider_id="mangachan",
                provider_manga_id=provider_manga_id,
                chapters=[],
                total=0,
                page=page,
                limit=limit,
                has_next=False,
            )

        slug = provider_manga_id.strip()
        html_content = await self._client.get_manga(slug)
        all_chapters = self._parse_chapters_from_html(slug, html_content)

        start = (page - 1) * limit
        paginated = all_chapters[start : start + limit]
        has_next = len(all_chapters) > (start + limit)

        return ProviderChaptersResult(
            provider_id="mangachan",
            provider_manga_id=slug,
            chapters=paginated,
            total=len(all_chapters),
            page=page,
            limit=limit,
            has_next=has_next,
        )

    async def get_chapter_pages(
        self,
        provider_chapter_id: str,
        data_saver: bool = False,
    ) -> ProviderPagesResult:
        ch_id = provider_chapter_id.strip()
        html_content = await self._client.get_chapter(ch_id)

        idx = html_content.find('"fullimg"')
        if idx == -1:
            raise ProviderNotFoundError(f"No pages found for chapter '{ch_id}' on Manga-Chan")

        arr_start = html_content.find("[", idx)
        arr_end = html_content.find("]", arr_start)
        raw_arr = html_content[arr_start : arr_end + 1]

        image_urls = re.findall(r'"(https?://[^"]+)"', raw_arr)
        if not image_urls:
            raise ProviderNotFoundError(f"Empty pages list for chapter '{ch_id}' on Manga-Chan")

        pages = [
            ProviderPageItem(page_number=i, image_url=url)
            for i, url in enumerate(image_urls, start=1)
        ]

        return ProviderPagesResult(
            provider_id="mangachan",
            provider_chapter_id=ch_id,
            pages=pages,
            data_saver=data_saver,
            expires_at=None,
        )

    async def close(self) -> None:
        await self._client.close()
