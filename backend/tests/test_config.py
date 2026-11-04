"""
Tests for configuration, SQLite path customization and CORS.
"""

import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from database.connection import get_connection, get_database_path, init_db
from main import app

client = TestClient(app)


def test_cors_headers_production():
    """CORS should allow requests from onigiri.punk.uz."""
    response = client.options(
        "/api/health",
        headers={
            "Origin": "https://onigiri.punk.uz",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "https://onigiri.punk.uz"


def test_custom_sqlite_db_path():
    """Database path should be configurable via SQLITE_DB_PATH environment variable."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        custom_db = Path(tmp_dir) / "subfolder" / "custom_test.db"
        old_env = os.environ.get("SQLITE_DB_PATH")
        os.environ["SQLITE_DB_PATH"] = str(custom_db)

        try:
            assert get_database_path() == custom_db
            init_db()
            assert custom_db.exists()

            # Verify table creation and data persistence
            conn = get_connection()
            conn.execute("INSERT INTO manga (title, description) VALUES (?, ?)", ("Test Manga", "Test Desc"))
            conn.commit()
            conn.close()

            # Re-open connection to verify persistence
            conn2 = get_connection()
            row = conn2.execute("SELECT title, description FROM manga WHERE title = ?", ("Test Manga",)).fetchone()
            assert row is not None
            assert row["title"] == "Test Manga"
            conn2.close()
        finally:
            if old_env is not None:
                os.environ["SQLITE_DB_PATH"] = old_env
            else:
                os.environ.pop("SQLITE_DB_PATH", None)
