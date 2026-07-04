import json
import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.database import EventLogEntry
from app.schemas import EventCreate, EventResponse
from app.services.redis_stream import redis_publisher

EVENT_RECEIVED = "Event received"
PUBLISHED_TO_STREAM = "Publish to stream"


def _append_log_entry(
    db: Session,
    *,
    event_id: str,
    event_type: str,
    source: str,
    payload_json: str,
    entry_status: str,
    redis_stream_id: str | None = None,
) -> EventLogEntry:
    entry = EventLogEntry(
        id=str(uuid.uuid4()),
        event_id=event_id,
        type=event_type,
        source=source,
        payload=payload_json,
        status=entry_status,
        redis_stream_id=redis_stream_id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def create_event(db: Session, event: EventCreate) -> EventResponse:
    event_id = str(uuid.uuid4())
    payload_json = json.dumps(event.payload)

    received_entry = _append_log_entry(
        db,
        event_id=event_id,
        event_type=event.type,
        source=event.source,
        payload_json=payload_json,
        entry_status=EVENT_RECEIVED,
    )

    try:
        stream_id = redis_publisher.publish(
            event_id=event_id,
            event_type=event.type,
            source=event.source,
            payload=event.payload,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": str(exc),
                "event_id": event_id,
                "status": EVENT_RECEIVED,
                "note": "Event was persisted to the database but not published to Redis.",
            },
        ) from exc

    published_entry = _append_log_entry(
        db,
        event_id=event_id,
        event_type=event.type,
        source=event.source,
        payload_json=payload_json,
        entry_status=PUBLISHED_TO_STREAM,
        redis_stream_id=stream_id,
    )

    return EventResponse(
        id=event_id,
        type=published_entry.type,
        source=published_entry.source,
        payload=json.loads(published_entry.payload),
        status=published_entry.status,
        redis_stream_id=published_entry.redis_stream_id,
        created_at=received_entry.created_at.isoformat(),
    )
