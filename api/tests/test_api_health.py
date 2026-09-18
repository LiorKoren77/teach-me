from __future__ import annotations

from fastapi.testclient import TestClient

from index import app


def test_health():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "teach-me"}
