import json

import httpx
import pytest
from sqlalchemy.orm import Session

from app.database import DeliveryAttemptRecord, DeliveryRecord
from app.services.delivery_record_service import DELIVERY_DELIVERED
from app.services.event_service import PUBLISHED_TO_STREAM

pytestmark = pytest.mark.integration


def test_e2e_post_events_consumer_delivers_webhook_notification(
    client,
    auth_header,
    integration_event_payload,
    real_redis_publisher,
    real_redis_client,
    real_redis_settings,
    real_stream_consumer,
    db_session: Session,
    monkeypatch,
):
    stream_name = real_redis_settings["stream_name"]
    webhook_url = "https://example.com/integration-webhook"
    webhook_calls: list[dict] = []

    monkeypatch.setattr("app.services.event_service.redis_publisher", real_redis_publisher)

    def capture_webhook_post(url: str, json: dict, timeout: float) -> httpx.Response:
        webhook_calls.append({"url": url, "json": json, "timeout": timeout})
        request = httpx.Request("POST", url)
        return httpx.Response(status_code=200, request=request)

    monkeypatch.setattr(
        "app.services.webhook_delivery_service.httpx.post",
        capture_webhook_post,
    )

    subscriber_response = client.post(
        "/subscribers/create",
        json={
            "webhook_url": webhook_url,
            "filters": {
                "type": integration_event_payload["type"],
                "source": integration_event_payload["source"],
            },
        },
        headers=auth_header("integration-user"),
    )
    assert subscriber_response.status_code == 201
    subscriber_id = subscriber_response.json()["id"]

    event_response = client.post(
        "/events",
        json=integration_event_payload,
        headers=auth_header("integration-user"),
    )

    assert event_response.status_code == 201
    event_body = event_response.json()
    assert event_body["status"] == PUBLISHED_TO_STREAM
    assert event_body["redis_stream_id"]
    event_id = event_body["id"]
    stream_id = event_body["redis_stream_id"]

    try:
        stream_entries = real_redis_client.xrange(stream_name, stream_id, stream_id)
        assert len(stream_entries) == 1

        real_stream_consumer.ensure_consumer_group()
        real_stream_consumer._consume_once()

        delivery = (
            db_session.query(DeliveryRecord)
            .filter(
                DeliveryRecord.event_id == event_id,
                DeliveryRecord.subscriber_id == subscriber_id,
            )
            .one()
        )
        attempts = (
            db_session.query(DeliveryAttemptRecord)
            .filter(DeliveryAttemptRecord.delivery_id == delivery.id)
            .order_by(DeliveryAttemptRecord.attempt_number)
            .all()
        )

        assert delivery.status == DELIVERY_DELIVERED
        assert delivery.attempt_count == 1
        assert len(attempts) == 1
        assert attempts[0].http_status_code == 200
        assert len(webhook_calls) == 1
        assert webhook_calls[0]["url"] == webhook_url
        assert webhook_calls[0]["json"]["event_id"] == event_id
        assert webhook_calls[0]["json"]["type"] == integration_event_payload["type"]
        assert webhook_calls[0]["json"]["source"] == integration_event_payload["source"]
        assert webhook_calls[0]["json"]["payload"] == integration_event_payload["payload"]
        assert webhook_calls[0]["json"]["redis_stream_id"] == stream_id
    finally:
        real_redis_client.xdel(stream_name, stream_id)
