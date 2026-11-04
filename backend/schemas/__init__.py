"""
Pydantic schemas package for Onigiri.
"""

from schemas.manga import (
    AuthorBase,
    AuthorCreate,
    AuthorRead,
    ChapterBase,
    ChapterCreate,
    ChapterPageBase,
    ChapterPageCreate,
    ChapterPageRead,
    ChapterRead,
    GenreBase,
    GenreCreate,
    GenreRead,
    MangaBase,
    MangaCreate,
    MangaDetailRead,
    MangaListRead,
    MangaSourceBase,
    MangaSourceCreate,
    MangaSourceRead,
    MangaUpdate,
)

__all__ = [
    "AuthorBase",
    "AuthorCreate",
    "AuthorRead",
    "ChapterBase",
    "ChapterCreate",
    "ChapterPageBase",
    "ChapterPageCreate",
    "ChapterPageRead",
    "ChapterRead",
    "GenreBase",
    "GenreCreate",
    "GenreRead",
    "MangaBase",
    "MangaCreate",
    "MangaDetailRead",
    "MangaListRead",
    "MangaSourceBase",
    "MangaSourceCreate",
    "MangaSourceRead",
    "MangaUpdate",
]
