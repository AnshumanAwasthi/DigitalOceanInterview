import json

import pytest

from app.services.event_service import PUBLISHED_TO_STREAM

pytestmark = pytest.mark.integration


def test_post_events_publishes_to_real_redis_stream(
    client,
    auth_header,
    integration_event_payload,
    real_redis_publisher,
    real_redis_client,
    real_redis_settings,
    db_session,
    monkeypatch,
):
    stream_name = real_redis_settings["stream_name"]
    monkeypatch.setattr("app.services.event_service.redis_publisher", real_redis_publisher)

    response = client.post(
        "/events",
        json=integration_event_payload,
        headers=auth_header("integration-user"),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == PUBLISHED_TO_STREAM
    assert body["redis_stream_id"]

    try:
        entries = real_redis_client.xrange(
            stream_name,
            body["redis_stream_id"],
            body["redis_stream_id"],
        )
        assert len(entries) == 1

        _, fields = entries[0]
        assert fields["event_id"] == body["id"]
        assert fields["type"] == integration_event_payload["type"]
        assert fields["source"] == integration_event_payload["source"]
        assert json.loads(fields["payload"]) == integration_event_payload["payload"]
    finally:
        real_redis_client.xdel(stream_name, body["redis_stream_id"])
