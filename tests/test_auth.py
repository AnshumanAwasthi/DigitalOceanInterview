import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth import create_access_token, verify_jwt_token
from app.config import settings


def test_create_access_token_encodes_user_id():
    token = create_access_token("user-42")

    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    assert payload["sub"] == "user-42"


def test_create_access_token_supports_multiple_users():
    token_one = create_access_token("user-1")
    token_two = create_access_token("user-2")

    payload_one = jwt.decode(token_one, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    payload_two = jwt.decode(token_two, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])

    assert payload_one["sub"] == "user-1"
    assert payload_two["sub"] == "user-2"
    assert token_one != token_two


def test_create_access_token_can_expire():
    token = create_access_token("user-42", expires_minutes=-1)

    with pytest.raises(jwt.ExpiredSignatureError):
        jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def test_verify_jwt_token_rejects_missing_credentials():
    with pytest.raises(Exception) as exc_info:
        verify_jwt_token(None)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Missing bearer token"


def test_verify_jwt_token_rejects_invalid_token():
    from fastapi.security import HTTPAuthorizationCredentials

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-jwt")

    with pytest.raises(Exception) as exc_info:
        verify_jwt_token(credentials)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid bearer token"


def test_verify_jwt_token_rejects_token_without_subject():
    token = jwt.encode({}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    from fastapi.security import HTTPAuthorizationCredentials

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(Exception) as exc_info:
        verify_jwt_token(credentials)

    assert exc_info.value.status_code == 401


def test_verify_jwt_token_rejects_token_signed_with_wrong_secret():
    token = jwt.encode({"sub": "user-1"}, "wrong-secret-key", algorithm=settings.jwt_algorithm)
    from fastapi.security import HTTPAuthorizationCredentials

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(Exception) as exc_info:
        verify_jwt_token(credentials)

    assert exc_info.value.status_code == 401


def test_events_endpoint_rejects_missing_auth(client: TestClient, sample_event_payload: dict):
    response = client.post("/events", json=sample_event_payload)

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing bearer token"


def test_events_endpoint_rejects_invalid_auth(client: TestClient, sample_event_payload: dict):
    response = client.post(
        "/events",
        json=sample_event_payload,
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid bearer token"


def test_events_endpoint_rejects_expired_auth(client: TestClient, sample_event_payload: dict):
    expired_token = create_access_token("test-user", expires_minutes=-1)

    response = client.post(
        "/events",
        json=sample_event_payload,
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid bearer token"


def test_events_endpoint_accepts_tokens_for_different_users(
    client: TestClient,
    auth_header,
    sample_event_payload: dict,
    mock_redis_publish,
):
    mock_redis_publish()

    for user_id in ("user-1", "user-2"):
        response = client.post(
            "/events",
            json=sample_event_payload,
            headers=auth_header(user_id),
        )
        assert response.status_code == 201
