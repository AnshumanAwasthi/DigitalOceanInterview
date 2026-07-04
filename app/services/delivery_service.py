import logging
from typing import Any

from sqlalchemy.orm import Session

from app.services.delivery_record_service import (
    create_pending_delivery,
    mark_delivery_delivered,
    mark_delivery_failed,
    record_delivery_attempts,
)
from app.services.filter_service import filters_match
from app.services.subscriber_service import load_subscribers, parse_subscriber_filters
from app.services.webhook_delivery_service import deliver_webhook_with_retry

logger = logging.getLogger(__name__)


def deliver_event_to_matching_subscribers(
    db: Session,
    *,
    event_id: str,
    event_type: str,
    source: str,
    payload: dict[str, Any],
    redis_stream_id: str,
) -> int:
    event_body = {
        "event_id": event_id,
        "type": event_type,
        "source": source,
        "payload": payload,
        "redis_stream_id": redis_stream_id,
    }

    delivered_count = 0
    for record in load_subscribers(db):
        filters = parse_subscriber_filters(record.filters_json)
        if not filters_match(
            filters,
            event_type=event_type,
            source=source,
            payload=payload,
        ):
            continue

        delivery = create_pending_delivery(
            db,
            event_id=event_id,
            subscriber_id=record.id,
        )
        success, failure_reason, attempts = deliver_webhook_with_retry(
            record.webhook_url,
            event_body,
        )
        record_delivery_attempts(db, delivery.id, attempts)
        attempt_count = len(attempts)

        if success:
            mark_delivery_delivered(db, delivery, attempt_count=attempt_count)
            delivered_count += 1
            logger.info(
                "Delivered event %s to subscriber %s at %s",
                event_id,
                record.id,
                record.webhook_url,
            )
        else:
            mark_delivery_failed(
                db,
                delivery,
                failure_reason=failure_reason or "Delivery failed",
                attempt_count=attempt_count,
            )

    return delivered_count
