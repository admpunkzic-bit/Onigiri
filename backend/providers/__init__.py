"""
Providers package for Onigiri.
"""

from providers.base import (
    BaseMangaProvider,
    ProviderChapterItem,
    ProviderChaptersResult,
    ProviderConfigurationError,
    ProviderError,
    ProviderMangaItem,
    ProviderNetworkError,
    ProviderNotFoundError,
    ProviderPageItem,
    ProviderPagesResult,
    ProviderRateLimitError,
    ProviderSearchResult,
)
from providers.registry import ProviderRegistry

__all__ = [
    "BaseMangaProvider",
    "ProviderChapterItem",
    "ProviderChaptersResult",
    "ProviderConfigurationError",
    "ProviderError",
    "ProviderMangaItem",
    "ProviderNetworkError",
    "ProviderNotFoundError",
    "ProviderPageItem",
    "ProviderPagesResult",
    "ProviderRateLimitError",
    "ProviderSearchResult",
    "ProviderRegistry",
]
