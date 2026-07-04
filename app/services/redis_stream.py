import json

import redis
from redis.exceptions import RedisError

from app.config import settings


class RedisStreamPublisher:
    def __init__(self) -> None:
        self._client = redis.from_url(settings.redis_url, decode_responses=True)
        self._stream_name = settings.redis_stream_name

    def publish(self, event_id: str, event_type: str, source: str, payload: dict) -> str:
        try:
            stream_id = self._client.xadd(
                self._stream_name,
                {
                    "event_id": event_id,
                    "type": event_type,
                    "source": source,
                    "payload": json.dumps(payload),
                },
            )
        except RedisError as exc:
            raise RuntimeError("Failed to publish event to Redis stream") from exc

        return stream_id

    def ping(self) -> bool:
        try:
            return self._client.ping()
        except RedisError:
            return False


redis_publisher = RedisStreamPublisher()
