from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import EventLogEntry
from app.services.event_service import EVENT_RECEIVED, PUBLISHED_TO_STREAM


def test_create_event_success(
    client: TestClient,
    auth_header,
    sample_event_payload: dict,
    mock_redis_publish,
    db_session: Session,
):
    stream_id = mock_redis_publish("1717488000000-0")

    response = client.post(
        "/events",
        json=sample_event_payload,
        headers=auth_header("test-user"),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["type"] == sample_event_payload["type"]
    assert body["source"] == sample_event_payload["source"]
    assert body["payload"] == sample_event_payload["payload"]
    assert body["status"] == PUBLISHED_TO_STREAM
    assert body["redis_stream_id"] == stream_id
    assert body["created_at"]

    log_entries = (
        db_session.query(EventLogEntry)
        .filter(EventLogEntry.event_id == body["id"])
        .order_by(EventLogEntry.created_at)
        .all()
    )
    assert len(log_entries) == 2
    assert log_entries[0].status == EVENT_RECEIVED
    assert log_entries[0].redis_stream_id is None
    assert log_entries[1].status == PUBLISHED_TO_STREAM
    assert log_entries[1].redis_stream_id == stream_id


def test_create_event_appends_only_log_on_redis_failure(
    client: TestClient,
    auth_header,
    sample_event_payload: dict,
    mock_redis_publish_failure,
    db_session: Session,
):
    response = client.post(
        "/events",
        json=sample_event_payload,
        headers=auth_header("test-user"),
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["status"] == EVENT_RECEIVED
    assert detail["event_id"]

    log_entries = (
        db_session.query(EventLogEntry)
        .filter(EventLogEntry.event_id == detail["event_id"])
        .all()
    )
    assert len(log_entries) == 1
    assert log_entries[0].status == EVENT_RECEIVED
    assert log_entries[0].redis_stream_id is None


def test_create_event_validates_required_fields(client: TestClient, auth_header):
    response = client.post(
        "/events",
        json={"source": "web-app", "payload": {}},
        headers=auth_header(),
    )

    assert response.status_code == 422


def test_create_event_accepts_empty_payload(
    client: TestClient,
    auth_header,
    mock_redis_publish,
):
    mock_redis_publish()

    response = client.post(
        "/events",
        json={"type": "heartbeat", "source": "worker", "payload": {}},
        headers=auth_header(),
    )

    assert response.status_code == 201
    assert response.json()["payload"] == {}


def test_create_event_accepts_nested_payload(
    client: TestClient,
    auth_header,
    mock_redis_publish,
):
    mock_redis_publish()
    nested_payload = {
        "type": "order.created",
        "source": "checkout",
        "payload": {
            "order_id": "ord-1",
            "items": [{"sku": "abc", "qty": 2}],
            "metadata": {"region": "us-east"},
        },
    }

    response = client.post("/events", json=nested_payload, headers=auth_header())

    assert response.status_code == 201
    assert response.json()["payload"] == nested_payload["payload"]
