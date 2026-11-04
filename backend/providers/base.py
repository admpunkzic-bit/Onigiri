"""
Base abstractions, DTOs, and exceptions for external manga providers in Onigiri.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


# ==============================================================================
# Exceptions
# ==============================================================================

class ProviderError(Exception):
    """Base exception for all provider-related errors."""
    pass


class ProviderNotFoundError(ProviderError):
    """Raised when a requested manga or chapter is not found in the source."""
    pass


class ProviderRateLimitError(ProviderError):
    """Raised when provider rate limit is exceeded (HTTP 429)."""

    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class ProviderNetworkError(ProviderError):
    """Raised on connection failures, timeouts, or unexpected network issues."""

    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.original_error = original_error


class ProviderConfigurationError(ProviderError):
    """Raised when provider is misconfigured or lacks required settings."""
    pass


# ==============================================================================
# DTOs (Data Transfer Objects)
# ==============================================================================

class ProviderMangaItem(BaseModel):
    """Information about a manga title from an external provider."""
    provider_id: str = Field(..., description="Provider identifier, e.g. 'mangadex'")
    provider_manga_id: str = Field(..., description="External unique manga ID in provider")
    title: str = Field(..., description="Primary title")
    alt_titles: List[str] = Field(default_factory=list, description="Alternative titles for matching")
    description: Optional[str] = None
    cover_url: Optional[str] = None
    status: str = Field(default="unknown", description="ongoing, completed, hiatus, cancelled, unknown")
    release_year: Optional[int] = None
    authors: List[str] = Field(default_factory=list, description="Author names")
    artists: List[str] = Field(default_factory=list, description="Artist names")
    genres: List[str] = Field(default_factory=list, description="Genres / tags")
    available_languages: List[str] = Field(default_factory=list, description="Available translation languages")
    source_url: Optional[str] = Field(None, description="External web link to manga page")

    model_config = ConfigDict(frozen=True)


class ProviderSearchResult(BaseModel):
    """Paginated search results from an external provider."""
    provider_id: str
    items: List[ProviderMangaItem]
    total: int
    page: int
    limit: int
    has_next: bool

    model_config = ConfigDict(frozen=True)


class ProviderChapterItem(BaseModel):
    """
    Chapter item from an external source.
    Preserves raw string numbering alongside parsed float value.
    """
    provider_id: str
    provider_manga_id: str
    provider_chapter_id: str = Field(..., description="External chapter ID in provider")
    chapter_number_raw: Optional[str] = Field(
        None,
        description="Raw chapter string, e.g. '1', '1.5', 'Extra', 'Prologue', None",
    )
    chapter_number_numeric: Optional[float] = Field(
        None,
        description="Parsed numeric chapter value for sorting; None if unnumbered or special",
    )
    is_special: bool = Field(
        default=False,
        description="True for extras, specials, prologs, oneshots or unnumbered chapters",
    )
    volume_number: Optional[int] = None
    title: Optional[str] = Field(None, description="Original chapter title if available")
    language: str = Field(..., description="Language code, e.g. 'ru'")
    scanlation_group: Optional[str] = Field(None, description="Scanlation group / translator name")
    published_at: Optional[datetime] = None

    model_config = ConfigDict(frozen=True)


class ProviderChaptersResult(BaseModel):
    """Paginated chapter list from an external provider."""
    provider_id: str
    provider_manga_id: str
    chapters: List[ProviderChapterItem]
    total: int
    page: int
    limit: int
    has_next: bool

    model_config = ConfigDict(frozen=True)


class ProviderPageItem(BaseModel):
    """Single page image URL."""
    page_number: int = Field(..., ge=1)
    image_url: str = Field(..., description="Direct page image URL")

    model_config = ConfigDict(frozen=True)


class ProviderPagesResult(BaseModel):
    """Result of requesting chapter pages."""
    provider_id: str
    provider_chapter_id: str
    pages: List[ProviderPageItem]
    data_saver: bool = False
    expires_at: Optional[datetime] = Field(
        None,
        description="Exact expiration time if provided by API; None if not reported",
    )

    model_config = ConfigDict(frozen=True)


# ==============================================================================
# Abstract Provider Interface
# ==============================================================================

class BaseMangaProvider(ABC):
    """
    Abstract base class for all manga providers.
    All methods are asynchronous and return standardized DTOs.
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique provider identifier (e.g. 'mangadex')."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name (e.g. 'MangaDex')."""
        pass

    @abstractmethod
    async def search(
        self,
        query: str,
        page: int = 1,
        limit: int = 20,
        languages: Optional[List[str]] = None,
    ) -> ProviderSearchResult:
        """Search manga titles matching query."""
        pass

    @abstractmethod
    async def get_manga_details(self, provider_manga_id: str) -> ProviderMangaItem:
        """Retrieve details and metadata for a specific manga."""
        pass

    @abstractmethod
    async def get_chapters(
        self,
        provider_manga_id: str,
        language: str = "ru",
        page: int = 1,
        limit: int = 100,
    ) -> ProviderChaptersResult:
        """Retrieve paginated chapter feed for a manga in requested language."""
        pass

    @abstractmethod
    async def get_chapter_pages(
        self,
        provider_chapter_id: str,
        data_saver: bool = False,
    ) -> ProviderPagesResult:
        """Retrieve page image URLs for reading a chapter."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close persistent HTTP sessions and release resources."""
        pass
