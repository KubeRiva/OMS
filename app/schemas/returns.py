"""Pydantic schemas for RMA returns and refunds."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.postgres.return_models import (
    ReturnCondition,
    ReturnReason,
    ReturnStatus,
    RefundMethod,
    RefundStatus,
)


# ---------------------------------------------------------------------------
# Return Item schemas
# ---------------------------------------------------------------------------

class ReturnItemCreate(BaseModel):
    sku: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1, max_length=500)
    quantity_requested: Decimal = Field(..., gt=0)
    order_item_id: Optional[UUID] = None
    restock: bool = True


class ReturnItemResponse(BaseModel):
    id: UUID
    return_id: UUID
    order_item_id: Optional[UUID] = None
    sku: str
    description: str
    quantity_requested: Decimal
    quantity_received: Optional[Decimal] = None
    condition: Optional[ReturnCondition] = None
    restock: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Refund schemas
# ---------------------------------------------------------------------------

class RefundCreate(BaseModel):
    refund_method: RefundMethod
    amount: Decimal = Field(..., gt=0)
    currency: str = Field(default="USD", max_length=3)
    transaction_id: Optional[str] = Field(default=None, max_length=200)
    reason: str = Field(..., min_length=1, max_length=500)
    notes: Optional[str] = None


class RefundUpdate(BaseModel):
    status: Optional[RefundStatus] = None
    transaction_id: Optional[str] = Field(default=None, max_length=200)
    processed_at: Optional[datetime] = None
    notes: Optional[str] = None


class RefundResponse(BaseModel):
    id: UUID
    refund_number: str
    order_id: UUID
    return_id: Optional[UUID] = None
    status: RefundStatus
    refund_method: RefundMethod
    amount: Decimal
    currency: str
    transaction_id: Optional[str] = None
    reason: str
    notes: Optional[str] = None
    processed_at: Optional[datetime] = None
    processed_by_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Return (OrderReturn) schemas
# ---------------------------------------------------------------------------

class ReturnCreate(BaseModel):
    order_id: UUID
    reason: ReturnReason
    customer_notes: Optional[str] = None
    items: List[ReturnItemCreate] = Field(..., min_length=1)


class ReturnUpdate(BaseModel):
    status: ReturnStatus
    staff_notes: Optional[str] = None
    return_tracking_number: Optional[str] = Field(default=None, max_length=100)
    return_carrier: Optional[str] = Field(default=None, max_length=50)


class ReturnResponse(BaseModel):
    id: UUID
    return_number: str
    order_id: UUID
    status: ReturnStatus
    reason: ReturnReason
    customer_notes: Optional[str] = None
    staff_notes: Optional[str] = None
    return_tracking_number: Optional[str] = None
    return_carrier: Optional[str] = None
    received_at: Optional[datetime] = None
    restocked_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    items: List[ReturnItemResponse] = []
    refund: Optional[RefundResponse] = None

    model_config = {"from_attributes": True}


class ReturnListResponse(BaseModel):
    items: List[ReturnResponse]
    total: int
