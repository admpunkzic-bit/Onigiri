"""
MangaLib Provider package for Onigiri.
"""

from providers.mangalib.client import MangaLibHttpClient
from providers.mangalib.provider import MangaLibProvider

__all__ = ["MangaLibHttpClient", "MangaLibProvider"]
