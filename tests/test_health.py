from fastapi.testclient import TestClient

from app.database import EventLogEntry
from app.services.event_service import EVENT_RECEIVED, PUBLISHED_TO_STREAM


def test_health_check_is_public(client: TestClient, monkeypatch):
    monkeypatch.setattr("app.main.redis_publisher.ping", lambda: True)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "redis": True}


def test_health_check_reports_redis_unavailable(client: TestClient, monkeypatch):
    monkeypatch.setattr("app.main.redis_publisher.ping", lambda: False)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "redis": False}
