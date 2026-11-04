"""
Provider registry management for Onigiri.
Managed within FastAPI lifecycle (startup/shutdown) without global mutable state.
"""

import asyncio
import logging
from typing import Dict, List

from providers.base import BaseMangaProvider, ProviderNotFoundError

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """
    Registry holding configured provider instances.
    Instantiated during FastAPI startup and stored in app.state.
    """

    def __init__(self):
        self._providers: Dict[str, BaseMangaProvider] = {}

    def register(self, provider: BaseMangaProvider) -> None:
        """Register a new provider instance."""
        self._providers[provider.provider_id] = provider
        logger.info(f"Registered provider '{provider.provider_id}' ({provider.name})")

    def get(self, provider_id: str) -> BaseMangaProvider:
        """Get provider instance by ID. Raises ProviderNotFoundError if not found."""
        if provider_id not in self._providers:
            raise ProviderNotFoundError(f"Provider '{provider_id}' is not registered")
        return self._providers[provider_id]

    def has(self, provider_id: str) -> bool:
        """Check if provider with given ID is registered."""
        return provider_id in self._providers

    def list_providers(self) -> List[Dict[str, str]]:
        """Return list of registered provider summaries."""
        return [
            {"id": p.provider_id, "name": p.name}
            for p in self._providers.values()
        ]

    async def close_all(self) -> None:
        """
        Safely close all registered providers during application shutdown.
        Uses return_exceptions=True to ensure all providers are closed
        even if one encounters an error during teardown.
        """
        if not self._providers:
            return

        logger.info(f"Closing {len(self._providers)} registered providers...")
        tasks = [provider.close() for provider in self._providers.values()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for provider, res in zip(self._providers.values(), results):
            if isinstance(res, Exception):
                logger.error(f"Error while closing provider '{provider.provider_id}': {res}")
            else:
                logger.debug(f"Provider '{provider.provider_id}' closed successfully.")
