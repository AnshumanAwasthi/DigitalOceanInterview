"""Standalone Redis stream consumer process."""

import logging
import signal
import sys

from app.database import init_db
from app.services.stream_consumer import stream_consumer

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def _handle_shutdown(signum: int, _frame) -> None:
    logger.info("Received signal %s, shutting down worker", signum)
    stream_consumer.stop()
    sys.exit(0)


def main() -> None:
    _configure_logging()
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    init_db()
    logger.info("Starting Redis stream worker")

    try:
        stream_consumer.run_forever()
    except Exception:
        logger.exception("Worker failed to start")
        sys.exit(1)


if __name__ == "__main__":
    main()
