"""
Database connection and session management for SQLite.
"""

import os
import sqlite3
from pathlib import Path

DEFAULT_DATABASE_PATH = Path(__file__).parent / "onigiri.db"


def get_database_path() -> Path:
    """Return the database path, allowing override via SQLITE_DB_PATH or DATABASE_PATH."""
    env_path = os.getenv("SQLITE_DB_PATH") or os.getenv("DATABASE_PATH")
    if env_path:
        path = Path(env_path)
    else:
        path = DEFAULT_DATABASE_PATH
    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_connection() -> sqlite3.Connection:
    """Create and return a new database connection."""
    conn = sqlite3.connect(str(get_database_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Initialize the database with base tables."""
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS manga (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                cover_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    finally:
        conn.close()
