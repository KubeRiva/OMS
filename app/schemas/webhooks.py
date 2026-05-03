from pydantic import BaseModel, Field, HttpUrl, model_validator
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class WebhookEndpointCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    url: str = Field(..., min_length=10)
    secret: str = Field(..., min_length=16, description="HMAC signing secret")
    is_active: bool = True
    event_types: List[str] = Field(
        default_factory=lambda: [
            "order.created", "order.confirmed", "order.sourced",
            "order.picking", "order.packed", "order.shipped",
            "order.delivered", "order.cancelled",
        ]
    )
    headers: dict = Field(default_factory=dict)


class WebhookEndpointUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    is_active: Optional[bool] = None
    event_types: Optional[List[str]] = None
    headers: Optional[dict] = None


class WebhookEndpointResponse(BaseModel):
    id: UUID
    name: str
    url: str
    is_active: bool
    event_types: list
    headers: dict
    retry_count: int
    created_at: datetime
    updated_at: datetime
    # secret is intentionally excluded — never returned to clients

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def strip_secret(cls, values):
        if isinstance(values, dict):
            values.pop("secret", None)
        return values


class WebhookEventResponse(BaseModel):
    id: UUID
    endpoint_id: UUID
    order_id: Optional[UUID] = None
    event_type: str
    status: str
    attempt_count: int
    next_retry_at: Optional[datetime] = None
    last_response_code: Optional[int] = None
    delivered_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WebhookDeliveryTest(BaseModel):
    endpoint_id: UUID
    event_type: str = "order.test"
    payload: Optional[dict] = None
