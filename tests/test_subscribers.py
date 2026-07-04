from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import SubscriberRecord
from app.services.filter_service import filters_match
from app.schemas import PayloadCondition, SubscriberFilters


def test_register_subscriber_with_all_filters(
    client: TestClient,
    auth_header,
    db_session: Session,
):
    payload = {
        "webhook_url": "https://example.com/webhooks/events",
        "filters": {
            "type": "user.signup",
            "source": "web-app",
            "payload_conditions": [
                {"field": "plan", "operator": "eq", "value": "pro"},
                {"field": "metadata.region", "operator": "eq", "value": "us-east"},
            ],
        },
    }

    response = client.post("/subscribers/create", json=payload, headers=auth_header("user-1"))

    assert response.status_code == 201
    body = response.json()
    assert body["webhook_url"] == payload["webhook_url"]
    assert body["filters"] == payload["filters"]
    assert body["owner_user_id"] == "user-1"
    assert body["id"]
    assert body["created_at"]

    record = db_session.get(SubscriberRecord, body["id"])
    assert record is not None
    assert record.webhook_url == payload["webhook_url"]


def test_register_subscriber_with_partial_filters(client: TestClient, auth_header):
    response = client.post(
        "/subscribers/create",
        json={
            "webhook_url": "https://hooks.example.com/all-signups",
            "filters": {"type": "user.signup"},
        },
        headers=auth_header(),
    )

    assert response.status_code == 201
    assert response.json()["filters"] == {
        "type": "user.signup",
        "source": None,
        "payload_conditions": [],
    }


def test_register_subscriber_requires_auth(client: TestClient):
    response = client.post(
        "/subscribers/create",
        json={"webhook_url": "https://example.com/webhook"},
    )

    assert response.status_code == 401


def test_register_subscriber_validates_webhook_url(client: TestClient, auth_header):
    response = client.post(
        "/subscribers/create",
        json={"webhook_url": "not-a-url"},
        headers=auth_header(),
    )

    assert response.status_code == 422


def test_filters_match_event_type_and_source():
    filters = SubscriberFilters(type="user.signup", source="web-app")

    assert filters_match(
        filters,
        event_type="user.signup",
        source="web-app",
        payload={},
    )
    assert not filters_match(
        filters,
        event_type="order.created",
        source="web-app",
        payload={},
    )


def test_filters_match_payload_conditions():
    filters = SubscriberFilters(
        payload_conditions=[
            PayloadCondition(field="plan", operator="eq", value="pro"),
            PayloadCondition(field="tags", operator="contains", value="beta"),
        ]
    )

    assert filters_match(
        filters,
        event_type="any",
        source="any",
        payload={"plan": "pro", "tags": ["beta", "internal"]},
    )
    assert not filters_match(
        filters,
        event_type="any",
        source="any",
        payload={"plan": "free", "tags": ["beta"]},
    )


def test_filters_match_nested_payload_field():
    filters = SubscriberFilters(
        payload_conditions=[
            PayloadCondition(field="metadata.region", operator="eq", value="us-east"),
        ]
    )

    assert filters_match(
        filters,
        event_type="user.signup",
        source="web-app",
        payload={"metadata": {"region": "us-east"}},
    )


def test_list_subscribers_returns_only_owned_records(client: TestClient, auth_header):
    client.post(
        "/subscribers/create",
        json={"webhook_url": "https://example.com/user-1-hook"},
        headers=auth_header("user-1"),
    )
    client.post(
        "/subscribers/create",
        json={"webhook_url": "https://example.com/user-2-hook"},
        headers=auth_header("user-2"),
    )

    user_one_response = client.get("/subscribers/list", headers=auth_header("user-1"))
    user_two_response = client.get("/subscribers/list", headers=auth_header("user-2"))

    assert user_one_response.status_code == 200
    assert user_two_response.status_code == 200
    assert len(user_one_response.json()) == 1
    assert len(user_two_response.json()) == 1
    assert user_one_response.json()[0]["owner_user_id"] == "user-1"
    assert user_two_response.json()[0]["owner_user_id"] == "user-2"


def test_list_subscribers_requires_auth(client: TestClient):
    response = client.get("/subscribers/list")

    assert response.status_code == 401


def test_delete_subscriber_success(client: TestClient, auth_header, db_session: Session):
    create_response = client.post(
        "/subscribers/create",
        json={"webhook_url": "https://example.com/to-delete"},
        headers=auth_header("user-1"),
    )
    subscriber_id = create_response.json()["id"]

    delete_response = client.delete(
        f"/subscribers/{subscriber_id}",
        headers=auth_header("user-1"),
    )

    assert delete_response.status_code == 204
    assert db_session.get(SubscriberRecord, subscriber_id) is None


def test_delete_subscriber_not_found(client: TestClient, auth_header):
    response = client.delete(
        "/subscribers/non-existent-id",
        headers=auth_header("user-1"),
    )

    assert response.status_code == 404


def test_delete_subscriber_rejects_other_users_subscriber(client: TestClient, auth_header):
    create_response = client.post(
        "/subscribers/create",
        json={"webhook_url": "https://example.com/user-1-hook"},
        headers=auth_header("user-1"),
    )
    subscriber_id = create_response.json()["id"]

    delete_response = client.delete(
        f"/subscribers/{subscriber_id}",
        headers=auth_header("user-2"),
    )

    assert delete_response.status_code == 404
