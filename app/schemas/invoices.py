"""Invoice schemas — B2B accounts receivable."""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.postgres.invoice_models import InvoiceStatus


class InvoiceCreate(BaseModel):
    customer_account_id: UUID
    order_id: Optional[UUID] = None
    notes: Optional[str] = None


class InvoiceStatusUpdate(BaseModel):
    status: InvoiceStatus
    notes: Optional[str] = None


class InvoiceLineItemResponse(BaseModel):
    id: UUID
    invoice_id: UUID
    order_item_id: Optional[UUID] = None
    sku: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    line_total: Decimal
    created_at: datetime
    model_config = {"from_attributes": True}


class PaymentCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    payment_date: date
    payment_method: str  # CHECK/WIRE/ACH/CREDIT_CARD/CASH/OTHER
    reference_number: Optional[str] = None
    notes: Optional[str] = None


class PaymentResponse(BaseModel):
    id: UUID
    invoice_id: UUID
    amount: Decimal
    payment_date: date
    payment_method: str
    reference_number: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class CreditMemoCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    reason: str
    notes: Optional[str] = None


class CreditMemoResponse(BaseModel):
    id: UUID
    memo_number: str
    customer_account_id: UUID
    invoice_id: Optional[UUID] = None
    status: str
    amount: Decimal
    currency: str
    reason: str
    notes: Optional[str] = None
    issued_date: Optional[date] = None
    applied_date: Optional[date] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class ARAgingBucket(BaseModel):
    count: int
    total_amount: Decimal


class ARAgingResponse(BaseModel):
    current: ARAgingBucket       # due_date >= today
    days_1_30: ARAgingBucket
    days_31_60: ARAgingBucket
    days_61_90: ARAgingBucket
    over_90: ARAgingBucket
    total_outstanding: Decimal


class InvoiceResponse(BaseModel):
    id: UUID
    invoice_number: str
    customer_account_id: UUID
    customer_account_name: Optional[str] = None
    order_id: Optional[UUID] = None
    order_number: Optional[str] = None
    status: InvoiceStatus
    subtotal: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    currency: str
    issued_date: date
    due_date: date
    paid_date: Optional[date] = None
    payment_terms: str
    notes: Optional[str] = None
    metadata: dict = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime
    line_items: List[InvoiceLineItemResponse] = Field(default_factory=list)
    amount_paid: float = 0.0
    amount_due: float = 0.0

    model_config = {"from_attributes": True, "populate_by_name": True}

    @classmethod
    def from_orm_with_relations(cls, invoice) -> "InvoiceResponse":
        obj = cls.model_validate(invoice)
        if invoice.customer_account:
            obj.customer_account_name = invoice.customer_account.company_name
        if invoice.order:
            obj.order_number = invoice.order.order_number
        return obj


class InvoiceListResponse(BaseModel):
    items: List[InvoiceResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
