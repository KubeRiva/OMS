"""
Inventory models: per-node stock levels, reservations, adjustments.
"""
import uuid
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime,
    Enum as SAEnum, Text, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.database.postgres import Base


class InventoryAdjustmentReason(str, enum.Enum):
    RECEIVED = "RECEIVED"
    SOLD = "SOLD"
    RETURNED = "RETURNED"
    DAMAGED = "DAMAGED"
    CYCLE_COUNT = "CYCLE_COUNT"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    RESERVED = "RESERVED"
    RESERVATION_RELEASED = "RESERVATION_RELEASED"
    CORRECTION = "CORRECTION"


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id = Column(UUID(as_uuid=True), ForeignKey("fulfillment_nodes.id"), nullable=False)
    sku = Column(String(100), nullable=False, index=True)
    product_name = Column(String(300))

    # Stock levels
    quantity_on_hand = Column(Integer, default=0, nullable=False)
    quantity_reserved = Column(Integer, default=0, nullable=False)
    quantity_available = Column(Integer, default=0, nullable=False)  # computed: on_hand - reserved
    quantity_on_order = Column(Integer, default=0)
    reorder_point = Column(Integer, default=10)
    reorder_quantity = Column(Integer, default=100)

    # Unit info
    unit_cost = Column(Float, default=0.0)
    weight_lbs = Column(Float, default=0.0)

    # Metadata
    is_active = Column(Boolean, default=True)
    last_counted_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    node = relationship("FulfillmentNode", back_populates="inventory_items")
    adjustments = relationship("InventoryAdjustment", back_populates="inventory_item", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("node_id", "sku", name="uq_inventory_node_sku"),
        Index("ix_inventory_sku_available", "sku", "quantity_available"),
        Index("ix_inventory_node_id", "node_id"),
    )


class InventoryAdjustment(Base):
    __tablename__ = "inventory_adjustments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    inventory_item_id = Column(UUID(as_uuid=True), ForeignKey("inventory_items.id"), nullable=False)
    reason = Column(SAEnum(InventoryAdjustmentReason), nullable=False)
    quantity_delta = Column(Integer, nullable=False)  # positive = add, negative = remove
    quantity_before = Column(Integer, nullable=False)
    quantity_after = Column(Integer, nullable=False)
    reference_id = Column(String(100))  # order_id, transfer_id, etc.
    notes = Column(Text)
    created_by = Column(String(100), default="system")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    inventory_item = relationship("InventoryItem", back_populates="adjustments")

    __table_args__ = (
        Index("ix_adj_inventory_item", "inventory_item_id"),
        Index("ix_adj_reference", "reference_id"),
    )


class InventoryReservation(Base):
    __tablename__ = "inventory_reservations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    order_item_id = Column(UUID(as_uuid=True), nullable=False)
    node_id = Column(UUID(as_uuid=True), ForeignKey("fulfillment_nodes.id"), nullable=False)
    sku = Column(String(100), nullable=False)
    quantity_reserved = Column(Integer, nullable=False)
    status = Column(String(50), default="ACTIVE")  # ACTIVE, COMMITTED, RELEASED
    expires_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_reservation_order", "order_id"),
        Index("ix_reservation_node_sku", "node_id", "sku"),
    )
