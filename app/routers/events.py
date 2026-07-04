from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.auth import verify_jwt_token
from app.database import get_db
from app.schemas import EventCreate, EventResponse
from app.services.event_service import create_event

router = APIRouter(
    prefix="/events",
    tags=["events"],
    dependencies=[Depends(verify_jwt_token)],
)


@router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
def ingest_event(event: EventCreate, db: Session = Depends(get_db)) -> EventResponse:
    """Ingest an event and persist it to SQLite and a Redis stream."""
    return create_event(db, event)
