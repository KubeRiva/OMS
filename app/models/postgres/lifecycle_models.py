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


class PipelineType(str, enum.Enum):
    ORDER  = "ORDER"
    RETURN = "RETURN"


class Lifecycle(Base):
    """
    A named pipeline governing allowed status transitions for orders.

    Resolution priority (first match wins):
      1. pipeline_type + order_type + brand_id + fulfillment_type + channel
      2. pipeline_type + order_type + fulfillment_type + channel
      3. pipeline_type + fulfillment_type match + channel match
      4. pipeline_type + fulfillment_type match
      5. default lifecycle (is_default=True)
    """
    __tablename__ = "lifecycles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    description = Column(Text)

    # Pipeline category
    pipeline_type = Column(String(20), default=PipelineType.ORDER.value, nullable=False)

    # Scope — empty/null means "all"
    fulfillment_types = Column(JSON, default=list)   # ["SHIP_TO_HOME"] etc.
    channels = Column(JSON, default=list)             # ["WEB","MOBILE"] etc.
    order_type = Column(String(20), nullable=True)    # "RETAIL"|"B2B"|"WHOLESALE"|null
    brand_id = Column(UUID(as_uuid=True), ForeignKey("brands.id"), nullable=True, index=True)

    # Custom status definitions for this pipeline
    # [{"key": "QUALITY_CHECK", "label": "Quality Check", "description": "...", "color": "#f59e0b"}]
    custom_statuses = Column(JSON, default=list)

    is_active = Column(Boolean, default=True, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)

    created_by = Column(String(100), default="system")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    steps = relationship(
        "LifecycleStep",
        back_populates="lifecycle",
        cascade="all, delete-orphan",
        order_by="LifecycleStep.step_order",
    )
    brand = relationship("Brand", foreign_keys=[brand_id], lazy="select")

    __table_args__ = (
        Index("ix_lifecycles_active", "is_active"),
        Index("ix_lifecycles_pipeline_type", "pipeline_type"),
        Index("ix_lifecycles_brand", "brand_id"),
    )


class LifecycleStep(Base):
    """
    One node in a lifecycle graph. status may reference a built-in OrderStatus
    value OR a key from the parent Lifecycle.custom_statuses list.

    action_type values:
      book_shipment        — trigger carrier worker
      send_pickup_ready    — notify customer + set pickup_ready_at
      simulate_delivery    — demo delivery simulation
      initiate_return      — create RMA record and notify warehouse
      notify_customer      — send generic customer notification
      none / null          — no automatic action
    """
    __tablename__ = "lifecycle_steps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lifecycle_id = Column(UUID(as_uuid=True), ForeignKey("lifecycles.id", ondelete="CASCADE"), nullable=False)

    status = Column(String(50), nullable=False)   # built-in or custom key
    label = Column(String(200), nullable=False)
    description = Column(Text, default="")
    step_order = Column(Integer, nullable=False, default=0)
    allowed_next_statuses = Column(JSON, default=list)
    action_type = Column(String(100), nullable=True)
    sla_hours = Column(Float, nullable=True)

    lifecycle = relationship("Lifecycle", back_populates="steps")

    __table_args__ = (
        Index("ix_lifecycle_steps_lifecycle_id", "lifecycle_id"),
    )
