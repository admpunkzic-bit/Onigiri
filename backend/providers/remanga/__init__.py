"""
ReManga Provider package for Onigiri.
"""

from providers.remanga.client import ReMangaHttpClient
from providers.remanga.provider import ReMangaProvider

__all__ = ["ReMangaHttpClient", "ReMangaProvider"]
