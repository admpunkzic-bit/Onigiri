"""
API routes for Onigiri backend.
"""

from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """Return the current server status."""
    return {
        "status": "ok",
        "service": "onigiri-api",
        "version": "0.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
