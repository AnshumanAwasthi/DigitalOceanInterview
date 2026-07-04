import pytest
from redis.exceptions import RedisError

from app.services.stream_consumer import StreamConsumer


def test_run_forever_stops_when_stop_is_called(monkeypatch):
    consumer = StreamConsumer()
    monkeypatch.setattr(consumer, "_connect_and_prepare", lambda: None)

    def consume_once_and_stop():
        consumer.stop()

    monkeypatch.setattr(consumer, "_consume_once", consume_once_and_stop)

    consumer.run_forever()

    assert consumer.is_running is False


def test_run_forever_exits_when_redis_unavailable(monkeypatch):
    consumer = StreamConsumer()

    def fail_ping():
        raise RedisError("connection refused")

    monkeypatch.setattr(consumer._client, "ping", fail_ping)

    with pytest.raises(RedisError):
        consumer.run_forever()


def test_worker_main_exits_when_consumer_fails(monkeypatch):
    from app import worker

    monkeypatch.setattr(worker, "init_db", lambda: None)

    def fail_forever():
        raise RedisError("connection refused")

    monkeypatch.setattr(worker.stream_consumer, "run_forever", fail_forever)

    with pytest.raises(SystemExit) as exc_info:
        worker.main()

    assert exc_info.value.code == 1
