from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser, verify_jwt_token
from app.database import get_db
from app.schemas import SubscriberCreate, SubscriberResponse
from app.services.subscriber_service import create_subscriber, delete_subscriber, list_subscribers

router = APIRouter(
    prefix="/subscribers",
    tags=["subscribers"],
    dependencies=[Depends(verify_jwt_token)],
)


@router.post("/create", response_model=SubscriberResponse, status_code=status.HTTP_201_CREATED)
def register_subscriber(
    subscriber: SubscriberCreate,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(verify_jwt_token),
) -> SubscriberResponse:
    """Register a webhook subscriber with optional event filter rules."""
    return create_subscriber(db, subscriber, user)


@router.get("/list", response_model=list[SubscriberResponse])
def get_subscribers(
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(verify_jwt_token),
) -> list[SubscriberResponse]:
    """List webhook subscribers registered by the authenticated user."""
    return list_subscribers(db, user)


@router.delete("/{subscriber_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_subscriber(
    subscriber_id: str,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(verify_jwt_token),
) -> None:
    """Delete a webhook subscriber owned by the authenticated user."""
    delete_subscriber(db, subscriber_id, user)
