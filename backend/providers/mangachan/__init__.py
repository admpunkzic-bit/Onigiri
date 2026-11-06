"""
Manga-Chan provider package for Onigiri.
"""

from providers.mangachan.client import MangaChanHttpClient, CircuitBreakerOpenError
from providers.mangachan.provider import MangaChanProvider

__all__ = [
    "MangaChanHttpClient",
    "MangaChanProvider",
    "CircuitBreakerOpenError",
]
