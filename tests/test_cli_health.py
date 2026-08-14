from fastapi.testclient import TestClient

from mahogany.cli import JOBS
from mahogany.health import app


def test_jobs_registered():
    assert "news" in JOBS
    assert "instagram" in JOBS
    assert "landing" in JOBS
    assert "group-bot" in JOBS


def test_build_id_endpoint(monkeypatch):
    monkeypatch.setenv("MAHOGANY_BUILD_ID", "test-sha")
    client = TestClient(app)
    r = client.get("/api/build-id")
    assert r.status_code == 200
    assert r.json()["buildId"] == "test-sha"
    assert r.json()["service"] == "mahogany"
