"""Sourcing rule and Distribution Group configuration models."""
import uuid
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime,
    Enum as SAEnum, Text, JSON, Index, ForeignKey, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.database.postgres import Base


class SourcingStrategy(str, enum.Enum):
    DISTANCE_OPTIMAL     = "DISTANCE_OPTIMAL"
    COST_OPTIMAL         = "COST_OPTIMAL"
    STORE_NEAREST        = "STORE_NEAREST"
    INVENTORY_RESERVATION = "INVENTORY_RESERVATION"
    LEAST_COST_SPLIT     = "LEAST_COST_SPLIT"
    AI_ADAPTIVE          = "AI_ADAPTIVE"
    AI_HYBRID            = "AI_HYBRID"


class ConditionOperator(str, enum.Enum):
    EQUALS                 = "EQUALS"
    NOT_EQUALS             = "NOT_EQUALS"
    GREATER_THAN           = "GREATER_THAN"
    LESS_THAN              = "LESS_THAN"
    GREATER_THAN_OR_EQUAL  = "GREATER_THAN_OR_EQUAL"
    LESS_THAN_OR_EQUAL     = "LESS_THAN_OR_EQUAL"
    IN                     = "IN"
    NOT_IN                 = "NOT_IN"
    CONTAINS               = "CONTAINS"
    STARTS_WITH            = "STARTS_WITH"


# ─── Distribution Groups ─────────────────────────────────────────────────────

class DistributionGroup(Base):
    """
    A logical group of fulfillment locations (nodes) that can be referenced
    as a single unit in sourcing rules.  Each member has a priority that
    controls the order in which the engine tries them.
    """
    __tablename__ = "distribution_groups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False)

    # Optional brand scope — null means usable by all brands
    brand_id = Column(UUID(as_uuid=True), ForeignKey("brands.id"), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    members = relationship(
        "DistributionGroupMember",
        back_populates="group",
        cascade="all, delete-orphan",
        order_by="DistributionGroupMember.priority",
    )
    brand = relationship("Brand", foreign_keys=[brand_id], lazy="select")

    __table_args__ = (
        Index("ix_distribution_groups_active", "is_active"),
        Index("ix_distribution_groups_brand", "brand_id"),
    )


class DistributionGroupMember(Base):
    """
    A fulfillment node that belongs to a DistributionGroup with an explicit
    priority.  Lower priority value = tried first by the sourcing engine.
    """
    __tablename__ = "distribution_group_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id = Column(
        UUID(as_uuid=True),
        ForeignKey("distribution_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_id = Column(
        UUID(as_uuid=True),
        ForeignKey("fulfillment_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Lower number = higher priority within this group
    priority = Column(Integer, default=1, nullable=False)

    group = relationship("DistributionGroup", back_populates="members")
    node = relationship("FulfillmentNode", lazy="joined")

    __table_args__ = (
        UniqueConstraint("group_id", "node_id", name="uq_dg_member_group_node"),
        Index("ix_dg_members_group_id", "group_id"),
        Index("ix_dg_members_node_id", "node_id"),
    )


# ─── Sourcing Rule ────────────────────────────────────────────────────────────

class SourcingRule(Base):
    """
    A configurable rule mapping order conditions to a sourcing strategy.
    Rules are evaluated in priority order (lower number = higher priority).

    sourcing_targets replaces the old allowed_node_types / excluded_node_ids
    approach with an explicit ordered list of DGs and/or individual nodes.
    Format:
      [
        {"type": "DISTRIBUTION_GROUP", "id": "<uuid>", "priority": 1},
        {"type": "NODE",               "id": "<uuid>", "priority": 2},
      ]
    When sourcing_targets is non-empty the engine resolves targets →
    candidate nodes in priority order.  The existing allowed_node_types and
    excluded_node_ids fields remain honoured as secondary filters.
    """
    __tablename__ = "sourcing_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    priority = Column(Integer, default=100, nullable=False)
    is_active = Column(Boolean, default=True)

    strategy = Column(SAEnum(SourcingStrategy), nullable=False)
    conditions = Column(JSON, default=list)

    # Legacy node filters (still honoured as secondary filters)
    allowed_node_types = Column(JSON, default=list)
    excluded_node_ids = Column(JSON, default=list)
    required_capabilities = Column(JSON, default=list)

    # Explicit ordered targets (DGs and/or individual nodes)
    sourcing_targets = Column(JSON, default=list)

    # Strategy parameters
    max_split_nodes = Column(Integer, default=3)
    max_distance_km = Column(Float)
    cost_weight = Column(Float, default=0.5)
    distance_weight = Column(Float, default=0.5)

    brand_id = Column(UUID(as_uuid=True), ForeignKey("brands.id"), nullable=True, index=True)

    created_by = Column(String(100), default="system")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    brand = relationship("Brand", back_populates="sourcing_rules", lazy="select")

    __table_args__ = (
        Index("ix_sourcing_rules_priority", "priority", "is_active"),
        Index("ix_sourcing_rules_brand", "brand_id"),
    )
