import json
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import DeliveryAttemptRecord, DeliveryRecord, SubscriberRecord
from app.services.delivery_record_service import (
    DELIVERY_DELIVERED,
    DELIVERY_FAILED,
    DELIVERY_PENDING,
)
from app.services.delivery_service import deliver_event_to_matching_subscribers
from app.services.stream_consumer import StreamConsumer
from app.services.webhook_delivery_service import WebhookAttemptResult


def _attempts(
    count: int,
    *,
    success_on_last: bool = True,
    http_status: int = 200,
    failure_reason: str = "server error",
) -> list[WebhookAttemptResult]:
    now = datetime.now(timezone.utc)
    results: list[WebhookAttemptResult] = []
    for index in range(count):
        is_success = success_on_last and index == count - 1
        results.append(
            WebhookAttemptResult(
                attempt_number=index + 1,
                http_status_code=http_status if is_success else 500,
                failure_reason=None if is_success else failure_reason,
                attempted_at=now,
            )
        )
    return results


def _create_subscriber(
    db_session: Session,
    *,
    webhook_url: str,
    owner_user_id: str,
    filters: dict,
    subscriber_id: str | None = None,
) -> SubscriberRecord:
    record = SubscriberRecord(
        id=subscriber_id or f"sub-{owner_user_id}",
        owner_user_id=owner_user_id,
        webhook_url=webhook_url,
        filters_json=json.dumps(filters),
    )
    db_session.add(record)
    db_session.commit()
    return record


def test_deliver_event_to_matching_subscribers_only(db_session: Session, monkeypatch):
    _create_subscriber(
        db_session,
        webhook_url="https://example.com/matching",
        owner_user_id="user-1",
        filters={"type": "user.signup", "source": "web-app", "payload_conditions": []},
    )
    _create_subscriber(
        db_session,
        webhook_url="https://example.com/non-matching",
        owner_user_id="user-2",
        filters={"type": "order.created", "source": "web-app", "payload_conditions": []},
    )

    delivered_urls: list[str] = []

    def fake_deliver(webhook_url: str, event: dict) -> tuple[bool, str | None, list[WebhookAttemptResult]]:
        delivered_urls.append(webhook_url)
        assert event["event_id"] == "event-1"
        assert event["type"] == "user.signup"
        return True, None, _attempts(1)

    monkeypatch.setattr(
        "app.services.delivery_service.deliver_webhook_with_retry",
        fake_deliver,
    )

    delivered_count = deliver_event_to_matching_subscribers(
        db_session,
        event_id="event-1",
        event_type="user.signup",
        source="web-app",
        payload={"plan": "pro"},
        redis_stream_id="1234-0",
    )

    assert delivered_count == 1
    assert delivered_urls == ["https://example.com/matching"]

    delivery = (
        db_session.query(DeliveryRecord)
        .filter(
            DeliveryRecord.event_id == "event-1",
            DeliveryRecord.subscriber_id == "sub-user-1",
        )
        .one()
    )
    assert delivery.status == DELIVERY_DELIVERED
    assert delivery.failure_reason is None
    assert delivery.attempt_count == 1
    assert len(delivery.attempts) == 1
    assert delivery.attempts[0].http_status_code == 200


def test_deliver_event_logs_failed_delivery(db_session: Session, monkeypatch):
    _create_subscriber(
        db_session,
        webhook_url="https://example.com/failing",
        owner_user_id="user-1",
        filters={"type": "user.signup", "source": "web-app", "payload_conditions": []},
    )

    monkeypatch.setattr(
        "app.services.delivery_service.deliver_webhook_with_retry",
        lambda *_args, **_kwargs: (False, "connection refused", _attempts(3, success_on_last=False, failure_reason="connection refused")),
    )

    delivered_count = deliver_event_to_matching_subscribers(
        db_session,
        event_id="event-fail",
        event_type="user.signup",
        source="web-app",
        payload={"plan": "pro"},
        redis_stream_id="1234-0",
    )

    assert delivered_count == 0
    delivery = (
        db_session.query(DeliveryRecord)
        .filter(DeliveryRecord.event_id == "event-fail")
        .one()
    )
    assert delivery.status == DELIVERY_FAILED
    assert delivery.failure_reason == "connection refused"
    assert delivery.attempt_count == 3
    assert len(delivery.attempts) == 3
    assert delivery.attempts[-1].failure_reason == "connection refused"


def test_deliver_event_skips_subscribers_when_payload_filter_fails(
    db_session: Session,
    monkeypatch,
):
    _create_subscriber(
        db_session,
        webhook_url="https://example.com/filtered",
        owner_user_id="user-1",
        filters={
            "type": "user.signup",
            "source": None,
            "payload_conditions": [{"field": "plan", "operator": "eq", "value": "pro"}],
        },
    )

    monkeypatch.setattr(
        "app.services.delivery_service.deliver_webhook_with_retry",
        lambda *_args, **_kwargs: (True, None, _attempts(1)),
    )

    delivered_count = deliver_event_to_matching_subscribers(
        db_session,
        event_id="event-2",
        event_type="user.signup",
        source="web-app",
        payload={"plan": "free"},
        redis_stream_id="1234-1",
    )

    assert delivered_count == 0
    assert db_session.query(DeliveryRecord).count() == 0


def test_deliver_event_creates_pending_before_delivery(db_session: Session, monkeypatch):
    _create_subscriber(
        db_session,
        webhook_url="https://example.com/hook",
        owner_user_id="user-1",
        filters={"type": "user.signup", "source": "web-app", "payload_conditions": []},
    )
    seen_statuses: list[str] = []

    def fake_deliver(webhook_url: str, event: dict) -> tuple[bool, str | None, list[WebhookAttemptResult]]:
        delivery = (
            db_session.query(DeliveryRecord)
            .filter(DeliveryRecord.event_id == event["event_id"])
            .one()
        )
        seen_statuses.append(delivery.status)
        return True, None, _attempts(1)

    monkeypatch.setattr(
        "app.services.delivery_service.deliver_webhook_with_retry",
        fake_deliver,
    )

    deliver_event_to_matching_subscribers(
        db_session,
        event_id="event-pending",
        event_type="user.signup",
        source="web-app",
        payload={},
        redis_stream_id="1234-0",
    )

    assert seen_statuses == [DELIVERY_PENDING]


def test_deliver_webhook_posts_event_payload(monkeypatch):
    captured: dict = {}

    def fake_post(url: str, json: dict, timeout: float) -> httpx.Response:
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        request = httpx.Request("POST", url)
        return httpx.Response(status_code=200, request=request)

    monkeypatch.setattr("app.services.webhook_delivery_service.httpx.post", fake_post)

    from app.services.webhook_delivery_service import deliver_webhook

    event = {
        "event_id": "event-1",
        "type": "user.signup",
        "source": "web-app",
        "payload": {"user_id": "123"},
        "redis_stream_id": "1234-0",
    }

    success, failure_reason, http_status_code = deliver_webhook("https://example.com/hook", event)
    assert success is True
    assert failure_reason is None
    assert http_status_code == 200
    assert captured["url"] == "https://example.com/hook"
    assert captured["json"] == event


def test_calculate_retry_delay_uses_exponential_backoff(monkeypatch):
    monkeypatch.setattr("app.services.webhook_delivery_service.settings.webhook_retry_base_seconds", 1.0)
    monkeypatch.setattr("app.services.webhook_delivery_service.settings.webhook_retry_max_seconds", 30.0)

    from app.services.webhook_delivery_service import calculate_retry_delay

    assert calculate_retry_delay(0) == 1.0
    assert calculate_retry_delay(1) == 2.0
    assert calculate_retry_delay(2) == 4.0
    assert calculate_retry_delay(5) == 30.0


def test_deliver_webhook_with_retry_succeeds_after_failures(monkeypatch):
    attempts = {"count": 0}
    sleeps: list[float] = []

    def fake_deliver(_webhook_url: str, _event: dict) -> tuple[bool, str | None, int | None]:
        attempts["count"] += 1
        if attempts["count"] >= 3:
            return True, None, 200
        return False, "temporary error", 500

    monkeypatch.setattr(
        "app.services.webhook_delivery_service.deliver_webhook",
        fake_deliver,
    )
    monkeypatch.setattr(
        "app.services.webhook_delivery_service.time.sleep",
        lambda delay: sleeps.append(delay),
    )
    monkeypatch.setattr("app.services.webhook_delivery_service.settings.webhook_max_retries", 3)

    from app.services.webhook_delivery_service import deliver_webhook_with_retry

    success, failure_reason, attempt_results = deliver_webhook_with_retry(
        "https://example.com/hook",
        {"event_id": "1"},
    )
    assert success is True
    assert failure_reason is None
    assert len(attempt_results) == 3
    assert attempt_results[0].http_status_code == 500
    assert attempt_results[-1].http_status_code == 200
    assert sleeps == [1.0, 2.0]


def test_deliver_webhook_with_retry_exhausts_retries(monkeypatch):
    sleeps: list[float] = []

    monkeypatch.setattr(
        "app.services.webhook_delivery_service.deliver_webhook",
        lambda *_args, **_kwargs: (False, "server error", 503),
    )
    monkeypatch.setattr(
        "app.services.webhook_delivery_service.time.sleep",
        lambda delay: sleeps.append(delay),
    )
    monkeypatch.setattr("app.services.webhook_delivery_service.settings.webhook_max_retries", 2)

    from app.services.webhook_delivery_service import deliver_webhook_with_retry

    success, failure_reason, attempt_results = deliver_webhook_with_retry(
        "https://example.com/hook",
        {"event_id": "1"},
    )
    assert success is False
    assert failure_reason == "server error"
    assert len(attempt_results) == 3
    assert all(attempt.http_status_code == 503 for attempt in attempt_results)
    assert sleeps == [1.0, 2.0]


def test_stream_consumer_processes_message(db_session: Session, monkeypatch):
    delivered: list[str] = []

    def fake_deliver(db, **kwargs):
        delivered.append(kwargs["event_id"])
        return 1

    monkeypatch.setattr(
        "app.services.stream_consumer.deliver_event_to_matching_subscribers",
        fake_deliver,
    )
    monkeypatch.setattr(
        "app.services.stream_consumer.SessionLocal",
        lambda: db_session,
    )

    consumer = StreamConsumer()
    consumer.process_message(
        "1717488000000-0",
        {
            "event_id": "event-99",
            "type": "user.signup",
            "source": "web-app",
            "payload": json.dumps({"plan": "pro"}),
        },
    )

    assert delivered == ["event-99"]


def test_delivery_history_by_event_id(client: TestClient, auth_header, db_session: Session):
    _create_subscriber(
        db_session,
        subscriber_id="sub-1",
        webhook_url="https://example.com/hook",
        owner_user_id="user-1",
        filters={"type": "user.signup", "source": "web-app", "payload_conditions": []},
    )
    db_session.add(
        DeliveryRecord(
            id="delivery-1",
            event_id="event-1",
            subscriber_id="sub-1",
            status=DELIVERY_DELIVERED,
            failure_reason=None,
            attempt_count=1,
        )
    )
    db_session.commit()

    response = client.get(
        "/deliveries/history?event_id=event-1",
        headers=auth_header("user-1"),
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["status"] == DELIVERY_DELIVERED
    assert body[0]["attempts"] == []


def test_delivery_history_includes_attempt_details(client: TestClient, auth_header, db_session: Session):
    _create_subscriber(
        db_session,
        subscriber_id="sub-1",
        webhook_url="https://example.com/hook",
        owner_user_id="user-1",
        filters={"type": "user.signup", "source": "web-app", "payload_conditions": []},
    )
    db_session.add(
        DeliveryRecord(
            id="delivery-1",
            event_id="event-1",
            subscriber_id="sub-1",
            status=DELIVERY_FAILED,
            failure_reason="server error",
            attempt_count=2,
        )
    )
    db_session.add(
        DeliveryAttemptRecord(
            id="attempt-1",
            delivery_id="delivery-1",
            attempt_number=1,
            http_status_code=500,
            failure_reason="server error",
            attempted_at=datetime(2026, 7, 4, 5, 0, 0, tzinfo=timezone.utc),
        )
    )
    db_session.add(
        DeliveryAttemptRecord(
            id="attempt-2",
            delivery_id="delivery-1",
            attempt_number=2,
            http_status_code=503,
            failure_reason="server error",
            attempted_at=datetime(2026, 7, 4, 5, 0, 2, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    response = client.get(
        "/deliveries/history?event_id=event-1&subscriber_id=sub-1",
        headers=auth_header("user-1"),
    )

    assert response.status_code == 200
    body = response.json()[0]
    assert body["status"] == DELIVERY_FAILED
    assert len(body["attempts"]) == 2
    assert body["attempts"][0]["http_status_code"] == 500
    assert body["attempts"][1]["attempt_number"] == 2
    assert body["attempts"][1]["attempted_at"] == "2026-07-04T05:00:02+00:00"


def test_query_deliveries_by_event_id(client: TestClient, auth_header, db_session: Session):
    _create_subscriber(
        db_session,
        subscriber_id="sub-1",
        webhook_url="https://example.com/hook",
        owner_user_id="user-1",
        filters={"type": "user.signup", "source": "web-app", "payload_conditions": []},
    )
    delivery = DeliveryRecord(
        id="delivery-1",
        event_id="event-1",
        subscriber_id="sub-1",
        status=DELIVERY_DELIVERED,
        failure_reason=None,
        attempt_count=1,
    )
    db_session.add(delivery)
    db_session.commit()

    response = client.get(
        "/deliveries/query?event_id=event-1",
        headers=auth_header("user-1"),
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["event_id"] == "event-1"
    assert body[0]["subscriber_id"] == "sub-1"
    assert body[0]["status"] == DELIVERY_DELIVERED
    assert "attempts" not in body[0]


def test_query_deliveries_by_subscriber_id(client: TestClient, auth_header, db_session: Session):
    _create_subscriber(
        db_session,
        subscriber_id="sub-1",
        webhook_url="https://example.com/hook",
        owner_user_id="user-1",
        filters={"type": "user.signup", "source": "web-app", "payload_conditions": []},
    )
    db_session.add(
        DeliveryRecord(
            id="delivery-1",
            event_id="event-1",
            subscriber_id="sub-1",
            status=DELIVERY_FAILED,
            failure_reason="timeout",
            attempt_count=3,
        )
    )
    db_session.commit()

    response = client.get(
        "/deliveries/query?subscriber_id=sub-1",
        headers=auth_header("user-1"),
    )

    assert response.status_code == 200
    assert response.json()[0]["status"] == DELIVERY_FAILED
    assert response.json()[0]["failure_reason"] == "timeout"
    assert "attempts" not in response.json()[0]


def test_query_deliveries_requires_filter(client: TestClient, auth_header):
    response = client.get("/deliveries/query", headers=auth_header("user-1"))

    assert response.status_code == 400


def test_query_deliveries_scoped_to_owner(client: TestClient, auth_header, db_session: Session):
    _create_subscriber(
        db_session,
        subscriber_id="sub-1",
        webhook_url="https://example.com/hook",
        owner_user_id="user-1",
        filters={"type": "user.signup", "source": "web-app", "payload_conditions": []},
    )
    db_session.add(
        DeliveryRecord(
            id="delivery-1",
            event_id="event-1",
            subscriber_id="sub-1",
            status=DELIVERY_DELIVERED,
            failure_reason=None,
            attempt_count=1,
        )
    )
    db_session.commit()

    response = client.get(
        "/deliveries/query?event_id=event-1",
        headers=auth_header("user-2"),
    )

    assert response.status_code == 200
    assert response.json() == []
