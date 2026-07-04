import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser
from app.database import SubscriberRecord
from app.schemas import SubscriberCreate, SubscriberFilters, SubscriberResponse


def _to_subscriber_response(record: SubscriberRecord) -> SubscriberResponse:
    return SubscriberResponse(
        id=record.id,
        webhook_url=record.webhook_url,
        filters=SubscriberFilters.model_validate_json(record.filters_json),
        owner_user_id=record.owner_user_id,
        created_at=record.created_at.isoformat(),
    )


def create_subscriber(
    db: Session,
    subscriber: SubscriberCreate,
    user: AuthenticatedUser,
) -> SubscriberResponse:
    filters = subscriber.filters
    record = SubscriberRecord(
        id=str(uuid.uuid4()),
        owner_user_id=user.user_id,
        webhook_url=str(subscriber.webhook_url),
        filters_json=filters.model_dump_json(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return _to_subscriber_response(record)


def list_subscribers(db: Session, user: AuthenticatedUser) -> list[SubscriberResponse]:
    records = (
        db.query(SubscriberRecord)
        .filter(SubscriberRecord.owner_user_id == user.user_id)
        .order_by(SubscriberRecord.created_at.desc())
        .all()
    )
    return [_to_subscriber_response(record) for record in records]


def delete_subscriber(db: Session, subscriber_id: str, user: AuthenticatedUser) -> None:
    record = db.get(SubscriberRecord, subscriber_id)
    if record is None or record.owner_user_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subscriber not found",
        )

    db.delete(record)
    db.commit()


def parse_subscriber_filters(filters_json: str) -> SubscriberFilters:
    return SubscriberFilters.model_validate_json(filters_json)


def load_subscribers(db: Session) -> list[SubscriberRecord]:
    return db.query(SubscriberRecord).all()
