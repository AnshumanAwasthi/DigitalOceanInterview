import json
import logging
import threading
import time
from typing import Any

import redis
from redis.exceptions import RedisError, ResponseError

from app.config import settings
from app.database import SessionLocal
from app.services.delivery_service import deliver_event_to_matching_subscribers

logger = logging.getLogger(__name__)


class StreamConsumer:
    def __init__(self) -> None:
        self._client = redis.from_url(settings.redis_url, decode_responses=True)
        self._stream_name = settings.redis_stream_name
        self._group_name = settings.redis_consumer_group
        self._consumer_name = settings.redis_consumer_name
        self._running = False
        self._thread: threading.Thread | None = None

    def ensure_consumer_group(self) -> None:
        try:
            self._client.xgroup_create(
                self._stream_name,
                self._group_name,
                id="0",
                mkstream=True,
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def process_message(self, message_id: str, fields: dict[str, Any]) -> None:
        payload = json.loads(fields["payload"])
        db = SessionLocal()
        try:
            delivered = deliver_event_to_matching_subscribers(
                db,
                event_id=fields["event_id"],
                event_type=fields["type"],
                source=fields["source"],
                payload=payload,
                redis_stream_id=message_id,
            )
            logger.info(
                "Processed stream message %s for event %s; delivered to %s subscriber(s)",
                message_id,
                fields["event_id"],
                delivered,
            )
        finally:
            db.close()

    def _consume_once(self) -> None:
        try:
            messages = self._client.xreadgroup(
                groupname=self._group_name,
                consumername=self._consumer_name,
                streams={self._stream_name: ">"},
                count=10,
                block=1000,
            )
        except RedisError as exc:
            logger.error("Failed to read from Redis stream: %s", exc)
            time.sleep(1)
            return

        if not messages:
            return

        for _stream, stream_messages in messages:
            for message_id, fields in stream_messages:
                try:
                    self.process_message(message_id, fields)
                    self._client.xack(self._stream_name, self._group_name, message_id)
                except Exception:
                    logger.exception(
                        "Failed to process stream message %s; leaving unacked for retry",
                        message_id,
                    )

    def _run_loop(self) -> None:
        while self._running:
            self._consume_once()

    def _connect_and_prepare(self) -> None:
        self._client.ping()
        self.ensure_consumer_group()

    def _log_started(self) -> None:
        logger.info(
            "Stream consumer started for stream=%s group=%s consumer=%s",
            self._stream_name,
            self._group_name,
            self._consumer_name,
        )

    def start(self) -> None:
        if not settings.consumer_enabled:
            logger.info("Stream consumer disabled by configuration")
            return

        try:
            self._connect_and_prepare()
        except RedisError as exc:
            logger.error("Stream consumer not started; Redis unavailable: %s", exc)
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name="redis-stream-consumer",
            daemon=True,
        )
        self._thread.start()
        self._log_started()

    def run_forever(self) -> None:
        """Block in the current thread and consume until stop() is called."""
        self._connect_and_prepare()
        self._running = True
        self._log_started()
        try:
            while self._running:
                self._consume_once()
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    @property
    def is_running(self) -> bool:
        return self._running


stream_consumer = StreamConsumer()
