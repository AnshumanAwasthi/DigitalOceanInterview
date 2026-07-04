from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class EventCreate(BaseModel):
    type: str = Field(..., min_length=1, max_length=255, examples=["user.signup"])
    source: str = Field(..., min_length=1, max_length=255, examples=["web-app"])
    payload: dict[str, Any] = Field(default_factory=dict, examples=[{"user_id": "123"}])


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    source: str
    payload: dict[str, Any]
    status: str
    redis_stream_id: str | None
    created_at: str


class PayloadCondition(BaseModel):
    field: str = Field(..., min_length=1, max_length=255, examples=["plan"])
    operator: Literal["eq", "neq", "contains", "exists"] = "eq"
    value: Any | None = None


class SubscriberFilters(BaseModel):
    type: str | None = Field(default=None, max_length=255, examples=["user.signup"])
    source: str | None = Field(default=None, max_length=255, examples=["web-app"])
    payload_conditions: list[PayloadCondition] = Field(default_factory=list)


class SubscriberCreate(BaseModel):
    webhook_url: HttpUrl = Field(..., examples=["https://example.com/webhooks/events"])
    filters: SubscriberFilters = Field(default_factory=SubscriberFilters)


class SubscriberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    webhook_url: str
    filters: SubscriberFilters
    owner_user_id: str
    created_at: str


DeliveryStatus = Literal["pending", "delivered", "failed"]


class DeliveryAttemptResponse(BaseModel):
    attempt_number: int
    http_status_code: int | None
    failure_reason: str | None
    attempted_at: str


class DeliveryHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str
    subscriber_id: str
    status: DeliveryStatus
    failure_reason: str | None
    attempt_count: int
    created_at: str
    updated_at: str
    attempts: list[DeliveryAttemptResponse]


class DeliveryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str
    subscriber_id: str
    status: DeliveryStatus
    failure_reason: str | None
    attempt_count: int
    created_at: str
    updated_at: str
