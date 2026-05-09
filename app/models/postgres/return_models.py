"""
Return and Refund models: RMA workflow + refund recording.
"""
import uuid
import enum
from datetime import datetime

from sqlalchemy import (
    Column, String, Boolean, DateTime, Numeric,
    Enum as SAEnum, Text, ForeignKey, Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.postgres import Base


class ReturnReason(str, enum.Enum):
    DEFECTIVE = "DEFECTIVE"
    WRONG_ITEM = "WRONG_ITEM"
    NOT_AS_DESCRIBED = "NOT_AS_DESCRIBED"
    CHANGED_MIND = "CHANGED_MIND"
    DUPLICATE_ORDER = "DUPLICATE_ORDER"
    DAMAGED_IN_TRANSIT = "DAMAGED_IN_TRANSIT"
    OTHER = "OTHER"


class ReturnStatus(str, enum.Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    RESTOCKED = "RESTOCKED"
    COMPLETED = "COMPLETED"


class ReturnCondition(str, enum.Enum):
    NEW = "NEW"
    GOOD = "GOOD"
    FAIR = "FAIR"
    DAMAGED = "DAMAGED"
    UNSELLABLE = "UNSELLABLE"


class RefundMethod(str, enum.Enum):
    ORIGINAL_PAYMENT = "ORIGINAL_PAYMENT"
    STORE_CREDIT = "STORE_CREDIT"
    BANK_TRANSFER = "BANK_TRANSFER"
    CHECK = "CHECK"
    OTHER = "OTHER"


class RefundStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class OrderReturn(Base):
    __tablename__ = "order_returns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # RMA-{YYYYMM}-{6hex}
    return_number = Column(String(50), unique=True, nullable=False, index=True)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, index=True)
    status = Column(SAEnum(ReturnStatus), default=ReturnStatus.REQUESTED, nullable=False, index=True)
    reason = Column(SAEnum(ReturnReason), nullable=False)
    customer_notes = Column(Text, nullable=True)
    staff_notes = Column(Text, nullable=True)
    return_tracking_number = Column(String(100), nullable=True)
    return_carrier = Column(String(50), nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=True)
    restocked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    order = relationship("Order", lazy="select")
    items = relationship(
        "ReturnItem",
        back_populates="order_return",
        cascade="all, delete-orphan",
        lazy="select",
    )
    refund = relationship("Refund", back_populates="order_return", uselist=False, lazy="select")

    __table_args__ = (
        Index("ix_order_returns_order", "order_id"),
    )


class ReturnItem(Base):
    __tablename__ = "return_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    return_id = Column(
        UUID(as_uuid=True),
        ForeignKey("order_returns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_item_id = Column(UUID(as_uuid=True), ForeignKey("order_items.id"), nullable=True)
    sku = Column(String(100), nullable=False)
    description = Column(String(500), nullable=False)
    quantity_requested = Column(Numeric(10, 3), nullable=False)
    quantity_received = Column(Numeric(10, 3), nullable=True)
    condition = Column(SAEnum(ReturnCondition), nullable=True)
    restock = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    order_return = relationship("OrderReturn", back_populates="items")


class Refund(Base):
    __tablename__ = "refunds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # REF-{YYYYMM}-{6hex}
    refund_number = Column(String(50), unique=True, nullable=False, index=True)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, index=True)
    # null = courtesy refund (no associated return)
    return_id = Column(UUID(as_uuid=True), ForeignKey("order_returns.id"), nullable=True, index=True)
    status = Column(SAEnum(RefundStatus), default=RefundStatus.PENDING, nullable=False, index=True)
    refund_method = Column(SAEnum(RefundMethod), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    # External payment processor reference
    transaction_id = Column(String(200), nullable=True)
    reason = Column(String(500), nullable=False)
    notes = Column(Text, nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    processed_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    order = relationship("Order", lazy="select")
    order_return = relationship("OrderReturn", back_populates="refund")
    processed_by = relationship("User", foreign_keys=[processed_by_id], lazy="select")

    __table_args__ = (
        Index("ix_refunds_order", "order_id"),
    )
