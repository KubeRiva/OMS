"""Lifecycle models — configurable per-fulfillment-type order pipelines."""
import uuid
import enum
from sqlalchemy import (
    Column, String, Boolean, Integer, Float, Text, DateTime,
    ForeignKey, JSON, Index, Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.postgres import Base


class Lifecycle(Base):
    """
    A named pipeline that governs allowed status transitions for orders
    matching a set of fulfillment types and/or channels.

    Resolution priority (first match wins):
      1. fulfillment_type match + channel match
      2. fulfillment_type match + no channel restriction
      3. default lifecycle (is_default=True)
    """
    __tablename__ = "lifecycles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    description = Column(Text)

    # Scope — empty list means "all"
    fulfillment_types = Column(JSON, default=list)   # ["SHIP_TO_HOME"] etc.
    channels = Column(JSON, default=list)             # ["WEB","MOBILE"] etc.

    is_active = Column(Boolean, default=True, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)  # fallback for unmatched types

    created_by = Column(String(100), default="system")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    steps = relationship(
        "LifecycleStep",
        back_populates="lifecycle",
        cascade="all, delete-orphan",
        order_by="LifecycleStep.step_order",
    )

    __table_args__ = (
        Index("ix_lifecycles_active", "is_active"),
    )


class LifecycleStep(Base):
    """
    One node in a lifecycle graph.  Each step names a status, the labels shown
    in the UI, which statuses may follow it, and an optional automated action
    the system should fire when the order enters this status.

    action_type values (handled by the lifecycle engine):
      book_shipment        — trigger carrier worker
      send_pickup_ready    — notify customer + set pickup_ready_at
      simulate_delivery    — demo delivery simulation
      none / null          — no automatic action
    """
    __tablename__ = "lifecycle_steps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lifecycle_id = Column(UUID(as_uuid=True), ForeignKey("lifecycles.id", ondelete="CASCADE"), nullable=False)

    # Which OrderStatus this step represents
    status = Column(String(50), nullable=False)

    label = Column(String(200), nullable=False)
    description = Column(Text, default="")

    # Ordering within the lifecycle
    step_order = Column(Integer, nullable=False, default=0)

    # Allowed outbound transitions from this step
    allowed_next_statuses = Column(JSON, default=list)  # ["PICKING", "CANCELLED"]

    # Automated action fired when the order ENTERS this status (nullable = no automation)
    action_type = Column(String(100), nullable=True)

    # Optional SLA budget in hours for this step
    sla_hours = Column(Float, nullable=True)

    lifecycle = relationship("Lifecycle", back_populates="steps")

    __table_args__ = (
        Index("ix_lifecycle_steps_lifecycle_id", "lifecycle_id"),
    )
