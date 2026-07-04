import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.auth import AuthenticatedUser
from app.database import DeliveryAttemptRecord, DeliveryRecord, SubscriberRecord
from app.services.webhook_delivery_service import WebhookAttemptResult

DELIVERY_PENDING = "pending"
DELIVERY_DELIVERED = "delivered"
DELIVERY_FAILED = "failed"


def create_pending_delivery(
    db: Session,
    *,
    event_id: str,
    subscriber_id: str,
) -> DeliveryRecord:
    now = datetime.now(timezone.utc)
    record = DeliveryRecord(
        id=str(uuid.uuid4()),
        event_id=event_id,
        subscriber_id=subscriber_id,
        status=DELIVERY_PENDING,
        failure_reason=None,
        attempt_count=0,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def record_delivery_attempts(
    db: Session,
    delivery_id: str,
    attempts: list[WebhookAttemptResult],
) -> None:
    for attempt in attempts:
        db.add(
            DeliveryAttemptRecord(
                id=str(uuid.uuid4()),
                delivery_id=delivery_id,
                attempt_number=attempt.attempt_number,
                http_status_code=attempt.http_status_code,
                failure_reason=attempt.failure_reason,
                attempted_at=attempt.attempted_at,
            )
        )
    db.commit()


def mark_delivery_delivered(
    db: Session,
    record: DeliveryRecord,
    *,
    attempt_count: int,
) -> DeliveryRecord:
    record.status = DELIVERY_DELIVERED
    record.failure_reason = None
    record.attempt_count = attempt_count
    record.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(record)
    return record


def mark_delivery_failed(
    db: Session,
    record: DeliveryRecord,
    *,
    failure_reason: str,
    attempt_count: int,
) -> DeliveryRecord:
    record.status = DELIVERY_FAILED
    record.failure_reason = failure_reason
    record.attempt_count = attempt_count
    record.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(record)
    return record


def _build_delivery_query(
    db: Session,
    user: AuthenticatedUser,
    *,
    event_id: str | None = None,
    subscriber_id: str | None = None,
):
    if not event_id and not subscriber_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide event_id and/or subscriber_id",
        )

    if subscriber_id is not None:
        subscriber = db.get(SubscriberRecord, subscriber_id)
        if subscriber is None or subscriber.owner_user_id != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Subscriber not found",
            )

    query = (
        db.query(DeliveryRecord)
        .join(SubscriberRecord, DeliveryRecord.subscriber_id == SubscriberRecord.id)
        .filter(SubscriberRecord.owner_user_id == user.user_id)
    )

    if event_id is not None:
        query = query.filter(DeliveryRecord.event_id == event_id)

    if subscriber_id is not None:
        query = query.filter(DeliveryRecord.subscriber_id == subscriber_id)

    return query.order_by(DeliveryRecord.created_at.desc())


def query_deliveries(
    db: Session,
    user: AuthenticatedUser,
    *,
    event_id: str | None = None,
    subscriber_id: str | None = None,
) -> list[DeliveryRecord]:
    return _build_delivery_query(
        db,
        user,
        event_id=event_id,
        subscriber_id=subscriber_id,
    ).all()


def query_delivery_history(
    db: Session,
    user: AuthenticatedUser,
    *,
    event_id: str | None = None,
    subscriber_id: str | None = None,
) -> list[DeliveryRecord]:
    return (
        _build_delivery_query(
            db,
            user,
            event_id=event_id,
            subscriber_id=subscriber_id,
        )
        .options(joinedload(DeliveryRecord.attempts))
        .all()
    )
