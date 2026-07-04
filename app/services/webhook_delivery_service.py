import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WebhookAttemptResult:
    attempt_number: int
    http_status_code: int | None
    failure_reason: str | None
    attempted_at: datetime


def calculate_retry_delay(attempt: int) -> float:
    delay = settings.webhook_retry_base_seconds * (2**attempt)
    return min(delay, settings.webhook_retry_max_seconds)


def deliver_webhook(
    webhook_url: str,
    event: dict[str, Any],
) -> tuple[bool, str | None, int | None]:
    try:
        response = httpx.post(
            webhook_url,
            json=event,
            timeout=settings.webhook_timeout_seconds,
        )
        response.raise_for_status()
        return True, None, response.status_code
    except httpx.HTTPStatusError as exc:
        logger.error("Webhook delivery failed for %s: %s", webhook_url, exc)
        return False, str(exc), exc.response.status_code
    except httpx.HTTPError as exc:
        logger.error("Webhook delivery failed for %s: %s", webhook_url, exc)
        return False, str(exc), None


def deliver_webhook_with_retry(
    webhook_url: str,
    event: dict[str, Any],
) -> tuple[bool, str | None, list[WebhookAttemptResult]]:
    max_retries = settings.webhook_max_retries
    last_failure_reason: str | None = None
    attempts: list[WebhookAttemptResult] = []

    for attempt in range(max_retries + 1):
        attempt_number = attempt + 1
        attempted_at = datetime.now(timezone.utc)
        success, failure_reason, http_status_code = deliver_webhook(webhook_url, event)
        attempts.append(
            WebhookAttemptResult(
                attempt_number=attempt_number,
                http_status_code=http_status_code,
                failure_reason=failure_reason if not success else None,
                attempted_at=attempted_at,
            )
        )

        if success:
            logger.info(
                "Webhook delivery succeeded for %s on attempt %s",
                webhook_url,
                attempt_number,
            )
            return True, None, attempts

        last_failure_reason = failure_reason
        if attempt < max_retries:
            delay = calculate_retry_delay(attempt)
            logger.warning(
                "Webhook delivery attempt %s failed for %s; retrying in %.1fs",
                attempt_number,
                webhook_url,
                delay,
            )
            time.sleep(delay)

    failure_reason = last_failure_reason or f"Exhausted {max_retries} retries"
    logger.error(
        "Webhook delivery exhausted %s retries for %s: %s",
        max_retries,
        webhook_url,
        failure_reason,
    )
    return False, failure_reason, attempts
