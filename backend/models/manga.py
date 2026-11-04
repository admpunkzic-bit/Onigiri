"""
Domain models and dataclasses for Onigiri Manga Catalog.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import sqlite3


@dataclass
class Genre:
    id: Optional[int]
    name: str
    slug: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Genre":
        return cls(
            id=row["id"],
            name=row["name"],
            slug=row["slug"],
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Author:
    id: Optional[int]
    name: str
    role: str = "author"
    created_at: Optional[str] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Author":
        # Handle cases where role might come from join or be absent
        keys = row.keys()
        return cls(
            id=row["id"],
            name=row["name"],
            role=row["role"] if "role" in keys else "author",
            created_at=row["created_at"] if "created_at" in keys else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ChapterPage:
    id: Optional[int]
    chapter_id: int
    page_number: int
    image_url: str
    created_at: Optional[str] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ChapterPage":
        keys = row.keys()
        return cls(
            id=row["id"],
            chapter_id=row["chapter_id"],
            page_number=row["page_number"],
            image_url=row["image_url"],
            created_at=row["created_at"] if "created_at" in keys else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Chapter:
    id: Optional[int]
    manga_id: int
    manga_source_id: int
    chapter_number: float
    volume_number: Optional[int] = None
    title: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    pages: List[ChapterPage] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Chapter":
        keys = row.keys()
        return cls(
            id=row["id"],
            manga_id=row["manga_id"],
            manga_source_id=row["manga_source_id"],
            chapter_number=float(row["chapter_number"]),
            volume_number=row["volume_number"] if "volume_number" in keys else None,
            title=row["title"] if "title" in keys else None,
            created_at=row["created_at"] if "created_at" in keys else None,
            updated_at=row["updated_at"] if "updated_at" in keys else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["pages"] = [p.to_dict() for p in self.pages]
        return data


@dataclass
class MangaSource:
    id: Optional[int]
    manga_id: int
    source_name: str
    source_manga_id: str
    source_url: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "MangaSource":
        keys = row.keys()
        return cls(
            id=row["id"],
            manga_id=row["manga_id"],
            source_name=row["source_name"],
            source_manga_id=row["source_manga_id"],
            source_url=row["source_url"] if "source_url" in keys else None,
            created_at=row["created_at"] if "created_at" in keys else None,
            updated_at=row["updated_at"] if "updated_at" in keys else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Manga:
    id: Optional[int]
    title: str
    slug: str
    original_title: Optional[str] = None
    description: Optional[str] = None
    cover_url: Optional[str] = None
    banner_url: Optional[str] = None
    status: str = "ongoing"
    type: str = "manga"
    release_year: Optional[int] = None
    rating: float = 0.0
    views_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    genres: List[Genre] = field(default_factory=list)
    authors: List[Author] = field(default_factory=list)
    sources: List[MangaSource] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Manga":
        keys = row.keys()
        return cls(
            id=row["id"],
            title=row["title"],
            slug=row["slug"] if "slug" in keys else f"manga-{row['id']}",
            original_title=row["original_title"] if "original_title" in keys else None,
            description=row["description"] if "description" in keys else None,
            cover_url=row["cover_url"] if "cover_url" in keys else None,
            banner_url=row["banner_url"] if "banner_url" in keys else None,
            status=row["status"] if "status" in keys else "ongoing",
            type=row["type"] if "type" in keys else "manga",
            release_year=row["release_year"] if "release_year" in keys else None,
            rating=float(row["rating"]) if "rating" in keys and row["rating"] is not None else 0.0,
            views_count=int(row["views_count"]) if "views_count" in keys and row["views_count"] is not None else 0,
            created_at=row["created_at"] if "created_at" in keys else None,
            updated_at=row["updated_at"] if "updated_at" in keys else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["genres"] = [g.to_dict() for g in self.genres]
        data["authors"] = [a.to_dict() for a in self.authors]
        data["sources"] = [s.to_dict() for s in self.sources]
        return data
