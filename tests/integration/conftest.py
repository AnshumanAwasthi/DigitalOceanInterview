import json
import os
import uuid
from pathlib import Path

import pytest
import redis
from dotenv import load_dotenv

from app.services.redis_stream import RedisStreamPublisher

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


@pytest.fixture(scope="session")
def real_redis_settings():
    load_dotenv(ENV_FILE, override=True)

    redis_url = os.getenv("REDIS_URL")
    stream_name = os.getenv("REDIS_STREAM_NAME", "events")

    if not redis_url:
        pytest.skip("REDIS_URL is not configured in .env")

    client = redis.from_url(redis_url, decode_responses=True)
    try:
        client.ping()
    except redis.RedisError as exc:
        pytest.skip(f"Redis is not reachable at {redis_url}: {exc}")

    return {"redis_url": redis_url, "stream_name": stream_name}


@pytest.fixture
def real_redis_client(real_redis_settings):
    client = redis.from_url(real_redis_settings["redis_url"], decode_responses=True)
    yield client
    client.close()


@pytest.fixture
def real_redis_publisher(real_redis_settings, monkeypatch):
    monkeypatch.setattr(
        "app.services.redis_stream.settings.redis_url",
        real_redis_settings["redis_url"],
    )
    monkeypatch.setattr(
        "app.services.redis_stream.settings.redis_stream_name",
        real_redis_settings["stream_name"],
    )
    return RedisStreamPublisher()


@pytest.fixture
def integration_event_payload():
    return {
        "type": "integration.test",
        "source": "pytest",
        "payload": {"test_run": "redis-stream-integration"},
    }


@pytest.fixture
def integration_consumer_group():
    return f"integration-{uuid.uuid4()}"


@pytest.fixture
def real_stream_consumer(real_redis_settings, integration_consumer_group, monkeypatch):
    monkeypatch.setattr(
        "app.services.stream_consumer.settings.redis_url",
        real_redis_settings["redis_url"],
    )
    monkeypatch.setattr(
        "app.services.stream_consumer.settings.redis_stream_name",
        real_redis_settings["stream_name"],
    )
    monkeypatch.setattr(
        "app.services.stream_consumer.settings.redis_consumer_group",
        integration_consumer_group,
    )
    monkeypatch.setattr(
        "app.services.stream_consumer.settings.redis_consumer_name",
        "integration-worker",
    )

    from app.services.stream_consumer import StreamConsumer

    return StreamConsumer()
