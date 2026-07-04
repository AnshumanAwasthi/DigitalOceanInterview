import os
import tempfile

import pytest
from fastapi.testclient import TestClient

_test_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_test_db.name}"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-at-least-32-chars-long"
os.environ["JWT_ALGORITHM"] = "HS256"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["REDIS_STREAM_NAME"] = "events"
os.environ["CONSUMER_ENABLED"] = "false"

from app.database import Base, SessionLocal, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def reset_database():
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_header():
    def _build_header(user_id: str = "test-user") -> dict[str, str]:
        from app.auth import create_access_token

        token = create_access_token(user_id)
        return {"Authorization": f"Bearer {token}"}

    return _build_header


@pytest.fixture
def sample_event_payload() -> dict:
    return {
        "type": "user.signup",
        "source": "web-app",
        "payload": {"user_id": "123", "plan": "pro"},
    }


@pytest.fixture
def mock_redis_publish(monkeypatch):
    def _apply(stream_id: str = "1717488000000-0"):
        monkeypatch.setattr(
            "app.services.event_service.redis_publisher.publish",
            lambda **_kwargs: stream_id,
        )
        return stream_id

    return _apply


@pytest.fixture
def mock_redis_publish_failure(monkeypatch):
    def _fail(**_kwargs):
        raise RuntimeError("Failed to publish event to Redis stream")

    monkeypatch.setattr("app.services.event_service.redis_publisher.publish", _fail)
