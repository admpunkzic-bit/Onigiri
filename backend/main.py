"""
Onigiri Backend — FastAPI application.
Manga reader Telegram Mini App.
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router as api_router
from database.connection import init_db
from providers.mangadex import MangaDexHttpClient, MangaDexProvider
from providers.registry import ProviderRegistry


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events: initialize database and providers on startup, clean shutdown."""
    init_db()

    # Initialize ProviderRegistry and register default providers
    registry = ProviderRegistry()
    mangadex_client = MangaDexHttpClient()
    mangadex_provider = MangaDexProvider(client=mangadex_client)
    registry.register(mangadex_provider)

    app.state.provider_registry = registry

    yield

    # Clean shutdown of all persistent provider HTTP sessions
    await registry.close_all()


app = FastAPI(
    title="Onigiri API",
    description="Backend API for Onigiri manga reader",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS configuration
DEFAULT_CORS_ORIGINS = [
    "https://onigiri.punk.uz",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

env_cors = os.getenv("CORS_ORIGINS")
if env_cors:
    allowed_origins = [origin.strip() for origin in env_cors.split(",") if origin.strip()]
else:
    allowed_origins = DEFAULT_CORS_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")
