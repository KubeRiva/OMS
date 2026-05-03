from pydantic import BaseModel, Field, EmailStr, field_validator, model_validator
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from decimal import Decimal
from app.models.postgres.order_models import (
    OrderChannel, FulfillmentType, OrderStatus, PaymentStatus,
    AllocationStatus, ShipmentStatus
)


class OrderItemCreate(BaseModel):
    sku: str = Field(..., min_length=1, max_length=100)
    product_name: str = Field(..., min_length=1)
    quantity: int = Field(..., ge=1)
    unit_price: Decimal = Field(..., ge=0)
    discount_amount: Decimal = Field(default=Decimal("0.00"), ge=0)
    tax_amount: Decimal = Field(default=Decimal("0.00"), ge=0)
    weight_lbs: float = Field(default=0.0, ge=0)
    metadata: dict = Field(default_factory=dict)


class ShippingAddressCreate(BaseModel):
    name: Optional[str] = None
    address1: str
    address2: Optional[str] = None
    city: str
    state: str
    postal_code: str
    country: str = "US"
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)


class OrderCreate(BaseModel):
    channel: OrderChannel
    fulfillment_type: FulfillmentType
    customer_email: EmailStr
    customer_phone: Optional[str] = None
    customer_name: Optional[str] = None
    customer_id: Optional[str] = None
    line_items: List[OrderItemCreate] = Field(..., min_length=1)
    shipping_address: Optional[ShippingAddressCreate] = None
    pickup_node_id: Optional[UUID] = None  # for BOPIS/curbside
    currency: str = Field(default="USD", max_length=3)
    discount_amount: Decimal = Field(default=Decimal("0.00"), ge=0)
    shipping_amount: Decimal = Field(default=Decimal("0.00"), ge=0)
    external_order_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    metadata: dict = Field(default_factory=dict)

    @field_validator("line_items")
    @classmethod
    def validate_line_items(cls, v):
        if not v:
            raise ValueError("Order must have at least one line item")
        return v

    @field_validator("pickup_node_id")
    @classmethod
    def validate_pickup_node(cls, v, info):
        # pickup_node_id required for pickup fulfillment types
        return v


class OrderUpdate(BaseModel):
    status: Optional[OrderStatus] = None
    payment_status: Optional[PaymentStatus] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None


class OrderItemResponse(BaseModel):
    id: UUID
    order_id: UUID
    sku: str
    product_name: str
    quantity: int
    quantity_fulfilled: int
    quantity_pending: int = 0
    quantity_allocated: int = 0
    quantity_backordered: int = 0
    quantity_shipped: int = 0
    quantity_delivered: int = 0
    status: str = "PENDING"
    unit_price: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    total_price: Decimal
    weight_lbs: float

    model_config = {"from_attributes": True}


class AllocationResponse(BaseModel):
    id: UUID
    order_id: UUID
    node_id: UUID
    node_code: Optional[str] = None
    node_name: Optional[str] = None
    sku: str
    quantity_allocated: int
    status: AllocationStatus
    allocated_at: datetime
    picking_started_at: Optional[datetime] = None
    packed_at: Optional[datetime] = None
    shipped_at: Optional[datetime] = None
    sourcing_score: Optional[float] = None

    @model_validator(mode='before')
    @classmethod
    def _extract_node(cls, v):
        if isinstance(v, dict):
            return v
        # Read ALL data via __dict__ to completely bypass SQLAlchemy descriptors
        # and avoid any lazy-load that would fail in a sync Pydantic context.
        d = v.__dict__
        node = d.get('node')
        node_d = node.__dict__ if node is not None else {}
        return {
            'id': d.get('id'),
            'order_id': d.get('order_id'),
            'node_id': d.get('node_id'),
            'node_code': node_d.get('code'),
            'node_name': node_d.get('name'),
            'sku': d.get('sku'),
            'quantity_allocated': d.get('quantity_allocated'),
            'status': d.get('status'),
            'allocated_at': d.get('allocated_at'),
            'picking_started_at': d.get('picking_started_at'),
            'packed_at': d.get('packed_at'),
            'shipped_at': d.get('shipped_at'),
            'sourcing_score': d.get('sourcing_score'),
        }

    model_config = {"from_attributes": True}


class ShipmentResponse(BaseModel):
    id: UUID
    order_id: UUID
    allocation_id: Optional[UUID] = None
    tracking_number: Optional[str] = None
    carrier: Optional[str] = None
    service_level: Optional[str] = None
    status: ShipmentStatus
    label_url: Optional[str] = None
    shipped_at: Optional[datetime] = None
    estimated_delivery_at: Optional[datetime] = None
    actual_delivery_at: Optional[datetime] = None
    shipping_cost: Optional[Decimal] = None
    line_items: List[dict] = []

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    id: UUID
    order_number: str
    channel: OrderChannel
    fulfillment_type: FulfillmentType
    status: OrderStatus
    payment_status: PaymentStatus
    customer_id: Optional[str] = None
    customer_email: str
    customer_phone: Optional[str] = None
    customer_name: Optional[str] = None
    subtotal: Decimal
    tax_amount: Decimal
    shipping_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    currency: str
    shipping_name: Optional[str] = None
    shipping_address1: Optional[str] = None
    shipping_address2: Optional[str] = None
    shipping_city: Optional[str] = None
    shipping_state: Optional[str] = None
    shipping_postal_code: Optional[str] = None
    shipping_country: Optional[str] = None
    pickup_node_id: Optional[UUID] = None
    pickup_ready_at: Optional[datetime] = None
    lifecycle_id: Optional[UUID] = None
    external_order_id: Optional[str] = None
    tags: list
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    confirmed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    line_items: List[OrderItemResponse] = []
    fulfillment_allocations: List[AllocationResponse] = []
    shipments: List[ShipmentResponse] = []

    model_config = {"from_attributes": True}


class OrderListResponse(BaseModel):
    items: List[OrderResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class OrderStatusUpdate(BaseModel):
    status: OrderStatus
    notes: Optional[str] = None


class CancelOrderRequest(BaseModel):
    reason: str
    notify_customer: bool = True


class OrderFilterParams(BaseModel):
    status: Optional[OrderStatus] = None
    channel: Optional[OrderChannel] = None
    fulfillment_type: Optional[FulfillmentType] = None
    customer_email: Optional[str] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
