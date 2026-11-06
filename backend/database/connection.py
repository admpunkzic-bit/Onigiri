"""
Database connection and session management for SQLite.
"""

import os
import sqlite3
from pathlib import Path

from database.migrations import run_migrations

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


def _unicode_lower(val: object) -> str:
    return str(val).lower() if val is not None else ""


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Create and return a new database connection with WAL and Foreign Keys enabled."""
    target_path = str(db_path) if db_path is not None else str(get_database_path())
    conn = sqlite3.connect(target_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.create_function("lower", 1, _unicode_lower)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | str | None = None) -> None:
    """Initialize the database schema by executing safe, versioned migrations."""
    conn = get_connection(db_path)
    try:
        run_migrations(conn)
    finally:
        conn.close()
