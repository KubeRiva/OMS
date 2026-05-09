"""
Core order models: Order, OrderItem, FulfillmentAllocation, Shipment, etc.
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Float, Boolean, DateTime, Integer,
    Enum as SAEnum, Text, ForeignKey, Index, JSON, Numeric
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from sqlalchemy.sql import func
import enum

from app.database.postgres import Base


class OrderChannel(str, enum.Enum):
    WEB = "WEB"
    MOBILE = "MOBILE"
    POS = "POS"
    API = "API"
    MARKETPLACE = "MARKETPLACE"
    B2B = "B2B"
    EDI = "EDI"
    WHOLESALE = "WHOLESALE"


class OrderType(str, enum.Enum):
    RETAIL = "RETAIL"
    WHOLESALE = "WHOLESALE"
    B2B = "B2B"
    INTERNAL = "INTERNAL"


class PaymentTerms(str, enum.Enum):
    PREPAID = "PREPAID"
    NET_15 = "NET_15"
    NET_30 = "NET_30"
    NET_60 = "NET_60"
    NET_90 = "NET_90"
    COD = "COD"
    UPON_RECEIPT = "UPON_RECEIPT"


class ApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class FulfillmentType(str, enum.Enum):
    SHIP_TO_HOME = "SHIP_TO_HOME"
    STORE_PICKUP = "STORE_PICKUP"           # BOPIS
    SHIP_FROM_STORE = "SHIP_FROM_STORE"
    CURBSIDE_PICKUP = "CURBSIDE_PICKUP"
    SAME_DAY_DELIVERY = "SAME_DAY_DELIVERY"
    FREIGHT = "FREIGHT"
    DROP_SHIP = "DROP_SHIP"


class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SOURCING = "SOURCING"
    SOURCED = "SOURCED"
    BACKORDERED = "BACKORDERED"
    PICKING = "PICKING"
    PACKING = "PACKING"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPPED = "SHIPPED"
    PARTIALLY_SHIPPED = "PARTIALLY_SHIPPED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    PARTIALLY_DELIVERED = "PARTIALLY_DELIVERED"
    DELIVERED = "DELIVERED"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


class OrderItemStatus(str, enum.Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    BACKORDERED = "BACKORDERED"
    PICKING = "PICKING"
    PACKING = "PACKING"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPPED = "SHIPPED"
    PARTIALLY_SHIPPED = "PARTIALLY_SHIPPED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    PARTIALLY_DELIVERED = "PARTIALLY_DELIVERED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class AllocationStatus(str, enum.Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    PICKING = "PICKING"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class ShipmentStatus(str, enum.Enum):
    PENDING = "PENDING"
    LABEL_CREATED = "LABEL_CREATED"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    EXCEPTION = "EXCEPTION"
    RETURNED = "RETURNED"


class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_number = Column(String(50), unique=True, nullable=False, index=True)
    channel = Column(SAEnum(OrderChannel), nullable=False)
    order_type = Column(String(20), default=OrderType.RETAIL.value, nullable=False)
    fulfillment_type = Column(SAEnum(FulfillmentType), nullable=False)
    status = Column(SAEnum(OrderStatus), default=OrderStatus.CONFIRMED, nullable=False)
    payment_status = Column(SAEnum(PaymentStatus), default=PaymentStatus.PENDING)

    # Customer (B2C transactional fields)
    customer_id = Column(String(100), index=True)
    customer_email = Column(String(255), nullable=False, index=True)
    customer_phone = Column(String(30))
    customer_name = Column(String(200))

    # B2B — linked account
    customer_account_id = Column(UUID(as_uuid=True), ForeignKey("customer_accounts.id"), nullable=True, index=True)

    # B2B — purchasing & approval
    po_number = Column(String(100), index=True)
    payment_terms = Column(String(20), default=PaymentTerms.PREPAID.value, nullable=False)
    approval_status = Column(String(20), default=ApprovalStatus.NOT_REQUIRED.value, nullable=False)
    approved_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True))
    payment_due_date = Column(DateTime(timezone=True))  # calculated from payment_terms + confirmed_at

    # B2B — billing address (may differ from shipping)
    billing_name = Column(String(200))
    billing_address1 = Column(String(255))
    billing_address2 = Column(String(255))
    billing_city = Column(String(100))
    billing_state = Column(String(100))
    billing_postal_code = Column(String(20))
    billing_country = Column(String(3), default="US")

    # Financial
    subtotal = Column(Numeric(12, 2), default=0)
    tax_amount = Column(Numeric(12, 2), default=0)
    shipping_amount = Column(Numeric(12, 2), default=0)
    discount_amount = Column(Numeric(12, 2), default=0)
    total_amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="USD")

    # Shipping Address
    shipping_name = Column(String(200))
    shipping_address1 = Column(String(255))
    shipping_address2 = Column(String(255))
    shipping_city = Column(String(100))
    shipping_state = Column(String(100))
    shipping_postal_code = Column(String(20))
    shipping_country = Column(String(3), default="US")
    shipping_latitude = Column(Float)
    shipping_longitude = Column(Float)

    # Pickup (for BOPIS/curbside)
    pickup_node_id = Column(UUID(as_uuid=True), ForeignKey("fulfillment_nodes.id"), nullable=True)
    pickup_ready_at = Column(DateTime(timezone=True))

    # Sourcing
    sourcing_rule_id = Column(UUID(as_uuid=True), ForeignKey("sourcing_rules.id"), nullable=True)
    sourcing_completed_at = Column(DateTime(timezone=True))

    # Lifecycle — which pipeline governs this order's status transitions
    lifecycle_id = Column(UUID(as_uuid=True), ForeignKey("lifecycles.id"), nullable=True)

    # Tracking
    external_order_id = Column(String(200), index=True)  # marketplace order ID
    connector_id = Column(UUID(as_uuid=True), ForeignKey("connectors.id"), nullable=True, index=True)
    tags = Column(JSON, default=list)
    notes = Column(Text)
    metadata_ = Column("metadata", JSON, default=dict)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    confirmed_at = Column(DateTime(timezone=True))
    cancelled_at = Column(DateTime(timezone=True))
    delivered_at = Column(DateTime(timezone=True))
    backordered_since = Column(DateTime(timezone=True), nullable=True)

    # Brand (optional — NULL means legacy/unbranded data)
    brand_id = Column(UUID(as_uuid=True), ForeignKey("brands.id"), nullable=True, index=True)

    # Seller brand (marketplace / B2B2C participant model):
    # who prices and fulfills this order; defaults to brand_id when null
    seller_brand_id = Column(UUID(as_uuid=True), ForeignKey("brands.id"), nullable=True)

    # Relationships
    brand        = relationship("Brand", back_populates="orders",       lazy="select", foreign_keys=[brand_id])
    seller_brand = relationship("Brand", back_populates="seller_orders", lazy="select", foreign_keys=[seller_brand_id])
    customer_account = relationship("CustomerAccount", back_populates="orders", foreign_keys=[customer_account_id])
    approved_by = relationship("User", foreign_keys=[approved_by_id])
    line_items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    fulfillment_allocations = relationship("FulfillmentAllocation", back_populates="order", cascade="all, delete-orphan")
    shipments = relationship("Shipment", back_populates="order", cascade="all, delete-orphan")
    webhook_events = relationship("WebhookEvent", back_populates="order", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_orders_status_created", "status", "created_at"),
        Index("ix_orders_channel_status", "channel", "status"),
        Index("ix_orders_brand", "brand_id"),
        Index("ix_orders_seller_brand", "seller_brand_id"),
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    sku = Column(String(100), nullable=False, index=True)
    product_name = Column(String(300), nullable=False)
    quantity = Column(Integer, nullable=False)
    
    # Quantity breakdown by status
    quantity_pending = Column(Integer, default=0)       # Not yet allocated (waiting for sourcing)
    quantity_allocated = Column(Integer, default=0)     # Allocated to nodes but not shipped
    quantity_backordered = Column(Integer, default=0)   # Could not be allocated (insufficient inventory)
    quantity_shipped = Column(Integer, default=0)       # Shipped to customer
    quantity_delivered = Column(Integer, default=0)     # Delivered to customer
    
    # Legacy field (keep for backward compatibility)
    quantity_fulfilled = Column(Integer, default=0)
    
    status = Column(SAEnum(OrderItemStatus), default=OrderItemStatus.PENDING)
    unit_price = Column(Numeric(12, 2), nullable=False)
    discount_amount = Column(Numeric(12, 2), default=0)
    tax_amount = Column(Numeric(12, 2), default=0)
    total_price = Column(Numeric(12, 2), nullable=False)
    weight_lbs = Column(Float, default=0.0)
    metadata_ = Column("metadata", JSON, default=dict)

    # Relationships
    order = relationship("Order", back_populates="line_items")
    fulfillment_allocations = relationship("FulfillmentAllocation", back_populates="order_item")

    __table_args__ = (
        Index("ix_order_items_order_id", "order_id"),
    )


class FulfillmentAllocation(Base):
    """Maps an order (or split portion) to a fulfillment node."""
    __tablename__ = "fulfillment_allocations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    order_item_id = Column(UUID(as_uuid=True), ForeignKey("order_items.id"), nullable=True)
    node_id = Column(UUID(as_uuid=True), ForeignKey("fulfillment_nodes.id"), nullable=False)
    sku = Column(String(100), nullable=False)
    quantity_allocated = Column(Integer, nullable=False)
    status = Column(SAEnum(AllocationStatus), default=AllocationStatus.PENDING)

    # Pipeline timestamps
    allocated_at = Column(DateTime(timezone=True), server_default=func.now())
    picking_started_at = Column(DateTime(timezone=True))
    packed_at = Column(DateTime(timezone=True))
    shipped_at = Column(DateTime(timezone=True))
    delivered_at = Column(DateTime(timezone=True))
    cancelled_at = Column(DateTime(timezone=True))

    # Sourcing score metadata
    sourcing_score = Column(Float)
    sourcing_metadata = Column(JSON, default=dict)

    # Relationships
    order = relationship("Order", back_populates="fulfillment_allocations")
    order_item = relationship("OrderItem", back_populates="fulfillment_allocations")
    node = relationship("FulfillmentNode", back_populates="fulfillment_allocations")

    __table_args__ = (
        Index("ix_allocations_order_id", "order_id"),
        Index("ix_allocations_node_status", "node_id", "status"),
    )


class Shipment(Base):
    __tablename__ = "shipments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    allocation_id = Column(UUID(as_uuid=True), ForeignKey("fulfillment_allocations.id"), nullable=True)
    tracking_number = Column(String(200), index=True)
    carrier = Column(String(100))
    service_level = Column(String(100))
    status = Column(SAEnum(ShipmentStatus), default=ShipmentStatus.PENDING)

    # Label
    label_url = Column(Text)
    label_created_at = Column(DateTime(timezone=True))

    # Tracking events (JSON array)
    tracking_events = Column(JSON, default=list)

    # Timestamps
    shipped_at = Column(DateTime(timezone=True))
    estimated_delivery_at = Column(DateTime(timezone=True))
    actual_delivery_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Cost
    shipping_cost = Column(Numeric(10, 2), default=0)

    # Relationships
    order = relationship("Order", back_populates="shipments")

    @property
    def line_items(self) -> list:
        """Return per-SKU line items for this shipment from the first tracking event."""
        events = self.tracking_events or []
        if events and isinstance(events[0], dict):
            return events[0].get("items", [])
        return []

    __table_args__ = (
        Index("ix_shipments_order_id", "order_id"),
        Index("ix_shipments_tracking", "tracking_number"),
    )


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    url = Column(Text, nullable=False)
    secret = Column(String(200), nullable=False)
    is_active = Column(Boolean, default=True)
    event_types = Column(JSON, default=list)  # ["order.created", "order.shipped", ...]
    headers = Column(JSON, default=dict)       # custom headers
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    events = relationship("WebhookEvent", back_populates="endpoint", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_webhook_endpoints_active", "is_active"),
    )


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    endpoint_id = Column(UUID(as_uuid=True), ForeignKey("webhook_endpoints.id"), nullable=False)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    event_type = Column(String(100), nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(String(50), default="PENDING")  # PENDING, DELIVERED, FAILED, RETRYING
    attempt_count = Column(Integer, default=0)
    next_retry_at = Column(DateTime(timezone=True))
    last_response_code = Column(Integer)
    last_response_body = Column(Text)
    delivered_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    endpoint = relationship("WebhookEndpoint", back_populates="events")
    order = relationship("Order", back_populates="webhook_events")

    __table_args__ = (
        Index("ix_webhook_events_status", "status", "next_retry_at"),
        Index("ix_webhook_events_order", "order_id"),
    )
