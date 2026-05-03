"""
Fulfillment nodes: Distribution Centers and Stores.
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Float, Boolean, DateTime, Integer,
    Enum as SAEnum, Text, ForeignKey, Index, JSON
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.database.postgres import Base


class NodeType(str, enum.Enum):
    DISTRIBUTION_CENTER = "DISTRIBUTION_CENTER"
    RETAIL_STORE = "RETAIL_STORE"
    DARK_STORE = "DARK_STORE"
    WAREHOUSE = "WAREHOUSE"
    PICKUP_POINT = "PICKUP_POINT"


class NodeStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    MAINTENANCE = "MAINTENANCE"
    CLOSED = "CLOSED"


class FulfillmentNode(Base):
    __tablename__ = "fulfillment_nodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    node_type = Column(SAEnum(NodeType), nullable=False)
    status = Column(SAEnum(NodeStatus), default=NodeStatus.ACTIVE, nullable=False)

    # Location
    address_line1 = Column(String(255))
    address_line2 = Column(String(255))
    city = Column(String(100))
    state = Column(String(100))
    postal_code = Column(String(20))
    country = Column(String(3), default="US")
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)

    # Capabilities
    can_ship = Column(Boolean, default=True)
    can_pickup = Column(Boolean, default=False)
    can_curbside = Column(Boolean, default=False)
    can_same_day = Column(Boolean, default=False)

    # Operational
    daily_order_capacity = Column(Integer, default=500)
    current_daily_orders = Column(Integer, default=0)
    avg_processing_hours = Column(Float, default=24.0)
    shipping_cost_multiplier = Column(Float, default=1.0)

    # Metadata
    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    inventory_items = relationship("InventoryItem", back_populates="node", cascade="all, delete-orphan")
    fulfillment_allocations = relationship("FulfillmentAllocation", back_populates="node")

    __table_args__ = (
        Index("ix_nodes_location", "latitude", "longitude"),
        Index("ix_nodes_type_status", "node_type", "status"),
    )
