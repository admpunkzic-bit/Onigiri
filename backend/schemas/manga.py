"""
Pydantic schemas for Manga catalog entities, validation and serialization.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


# ==========================================
# Genre Schemas
# ==========================================

class GenreBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=100)


class GenreCreate(GenreBase):
    pass


class GenreRead(GenreBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# Author Schemas
# ==========================================

class AuthorBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class AuthorCreate(AuthorBase):
    pass


class AuthorRead(AuthorBase):
    id: int
    role: Optional[str] = "author"

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# Chapter Page Schemas
# ==========================================

class ChapterPageBase(BaseModel):
    page_number: int = Field(..., ge=1)
    image_url: str = Field(..., min_length=1)


class ChapterPageCreate(ChapterPageBase):
    chapter_id: int


class ChapterPageRead(ChapterPageBase):
    id: int
    chapter_id: int
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# Chapter Schemas
# ==========================================

class ChapterBase(BaseModel):
    chapter_number: Optional[float] = Field(default=None, ge=0)
    volume_number: Optional[int] = Field(None, ge=0)
    title: Optional[str] = None
    source_chapter_id: Optional[str] = None
    canonical_chapter_id: Optional[int] = None
    language: Optional[str] = "ru"
    scanlation_group: Optional[str] = None
    published_at: Optional[datetime] = None


class ChapterCreate(ChapterBase):
    manga_id: int
    manga_source_id: int


class ChapterRead(ChapterBase):
    id: int
    manga_id: int
    manga_source_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    pages_count: Optional[int] = 0
    pages: Optional[List[ChapterPageRead]] = None

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# Manga Source Schemas
# ==========================================

class MangaSourceBase(BaseModel):
    source_name: str = Field(..., min_length=1, max_length=100)
    source_manga_id: str = Field(..., min_length=1, max_length=255)
    source_url: Optional[str] = None


class MangaSourceCreate(MangaSourceBase):
    manga_id: int


class MangaSourceRead(MangaSourceBase):
    id: int
    manga_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# Manga Schemas
# ==========================================

class MangaBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    slug: str = Field(..., min_length=1, max_length=500)
    original_title: Optional[str] = None
    description: Optional[str] = None
    cover_url: Optional[str] = None
    banner_url: Optional[str] = None
    status: str = Field(default="ongoing", description="ongoing, completed, hiatus, cancelled")
    type: str = Field(default="manga", description="manga, manhwa, manhua, one_shot")
    release_year: Optional[int] = None
    rating: float = Field(default=0.0, ge=0.0, le=10.0)
    views_count: int = Field(default=0, ge=0)


class MangaCreate(MangaBase):
    pass


class MangaUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    original_title: Optional[str] = None
    description: Optional[str] = None
    cover_url: Optional[str] = None
    banner_url: Optional[str] = None
    status: Optional[str] = None
    type: Optional[str] = None
    release_year: Optional[int] = None
    rating: Optional[float] = None
    views_count: Optional[int] = None


class MangaListRead(BaseModel):
    """Compact representation for catalog grids, search results, library."""
    id: int
    title: str
    slug: str
    original_title: Optional[str] = None
    cover_url: Optional[str] = None
    status: str
    type: str
    release_year: Optional[int] = None
    rating: float
    views_count: int
    genres: List[GenreRead] = []
    authors: List[AuthorRead] = []

    model_config = ConfigDict(from_attributes=True)


class MangaDetailRead(MangaListRead):
    """Full detailed representation with description, banners, sources and chapters."""
    description: Optional[str] = None
    banner_url: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    sources: List[MangaSourceRead] = []
    chapters: List[ChapterRead] = []

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# Reader & Reading Progress Schemas (TASK 012)
# ==========================================

class ChapterReaderPageItem(BaseModel):
    page_number: int
    image_url: str


class ChapterReaderDetailRead(BaseModel):
    chapter_id: int
    manga_id: int
    manga_title: str
    cover_url: Optional[str] = None
    manga_slug: Optional[str] = None
    chapter_number: Optional[float] = None
    volume_number: Optional[int] = None
    title: Optional[str] = None
    scanlation_group: Optional[str] = None
    total_pages: int
    pages: List[ChapterReaderPageItem] = []
    prev_chapter_id: Optional[int] = None
    next_chapter_id: Optional[int] = None


class ReadingProgressUpdate(BaseModel):
    chapter_id: int
    page_number: int = Field(default=1, ge=1)
    total_pages: Optional[int] = None


class ReadingProgressRead(BaseModel):
    manga_id: int
    chapter_id: int
    chapter_number: Optional[float] = None
    chapter_title: Optional[str] = None
    page_number: int
    total_pages: Optional[int] = None
    updated_at: str


class ReadingHistoryItemRead(BaseModel):
    manga_id: int
    manga_slug: str
    manga_title: str
    cover_url: Optional[str] = None
    manga_status: Optional[str] = "unknown"
    chapter_id: int
    chapter_number: Optional[float] = None
    volume_number: Optional[int] = None
    chapter_title: Optional[str] = None
    page_number: int
    total_pages: Optional[int] = None
    updated_at: str

    model_config = ConfigDict(from_attributes=True)
