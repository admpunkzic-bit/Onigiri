"""
Tests for the health endpoint.
"""

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health_returns_ok():
    """Health endpoint should return status ok."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "onigiri-api"
    assert data["version"] == "0.1.0"
    assert "timestamp" in data


def test_health_json_content_type():
    """Health endpoint should return JSON content type."""
    response = client.get("/api/health")
    assert "application/json" in response.headers["content-type"]
