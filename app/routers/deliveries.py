from datetime import timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser, verify_jwt_token
from app.database import get_db
from app.schemas import DeliveryAttemptResponse, DeliveryHistoryResponse, DeliveryResponse
from app.services.delivery_record_service import query_deliveries, query_delivery_history

router = APIRouter(
    prefix="/deliveries",
    tags=["deliveries"],
    dependencies=[Depends(verify_jwt_token)],
)


def _format_timestamp(value) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _to_delivery_response(record) -> DeliveryResponse:
    return DeliveryResponse(
        id=record.id,
        event_id=record.event_id,
        subscriber_id=record.subscriber_id,
        status=record.status,
        failure_reason=record.failure_reason,
        attempt_count=record.attempt_count,
        created_at=_format_timestamp(record.created_at),
        updated_at=_format_timestamp(record.updated_at),
    )


def _to_history_response(record) -> DeliveryHistoryResponse:
    return DeliveryHistoryResponse(
        id=record.id,
        event_id=record.event_id,
        subscriber_id=record.subscriber_id,
        status=record.status,
        failure_reason=record.failure_reason,
        attempt_count=record.attempt_count,
        created_at=_format_timestamp(record.created_at),
        updated_at=_format_timestamp(record.updated_at),
        attempts=[
            DeliveryAttemptResponse(
                attempt_number=attempt.attempt_number,
                http_status_code=attempt.http_status_code,
                failure_reason=attempt.failure_reason,
                attempted_at=_format_timestamp(attempt.attempted_at),
            )
            for attempt in record.attempts
        ],
    )


@router.get("/query", response_model=list[DeliveryResponse])
def get_deliveries(
    event_id: str | None = Query(default=None),
    subscriber_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(verify_jwt_token),
) -> list[DeliveryResponse]:
    """Query delivery status by event_id and/or subscriber_id."""
    records = query_deliveries(
        db,
        user,
        event_id=event_id,
        subscriber_id=subscriber_id,
    )
    return [_to_delivery_response(record) for record in records]


@router.get("/history", response_model=list[DeliveryHistoryResponse])
def get_delivery_history(
    event_id: str | None = Query(default=None),
    subscriber_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(verify_jwt_token),
) -> list[DeliveryHistoryResponse]:
    """Return delivery history per event and/or subscription, including attempt details."""
    records = query_delivery_history(
        db,
        user,
        event_id=event_id,
        subscriber_id=subscriber_id,
    )
    return [_to_history_response(record) for record in records]
