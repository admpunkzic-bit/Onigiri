"""
Database package for Onigiri.
"""

from database.connection import get_connection, get_database_path, init_db
from database.migrations import is_fts5_available, run_migrations, search_manga

__all__ = [
    "get_connection",
    "get_database_path",
    "init_db",
    "run_migrations",
    "is_fts5_available",
    "search_manga",
]
