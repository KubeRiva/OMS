"""
Sourcing rule configuration models.
"""
import uuid
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime,
    Enum as SAEnum, Text, JSON, Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import enum

from app.database.postgres import Base


class SourcingStrategy(str, enum.Enum):
    DISTANCE_OPTIMAL = "DISTANCE_OPTIMAL"
    COST_OPTIMAL = "COST_OPTIMAL"
    STORE_NEAREST = "STORE_NEAREST"
    INVENTORY_RESERVATION = "INVENTORY_RESERVATION"
    LEAST_COST_SPLIT = "LEAST_COST_SPLIT"
    AI_ADAPTIVE = "AI_ADAPTIVE"      # KubeAI-scored nodes using historical patterns
    AI_HYBRID = "AI_HYBRID"          # Blend AI score 60% + rule-based score 40%


class ConditionOperator(str, enum.Enum):
    EQUALS = "EQUALS"
    NOT_EQUALS = "NOT_EQUALS"
    GREATER_THAN = "GREATER_THAN"
    LESS_THAN = "LESS_THAN"
    GREATER_THAN_OR_EQUAL = "GREATER_THAN_OR_EQUAL"
    LESS_THAN_OR_EQUAL = "LESS_THAN_OR_EQUAL"
    IN = "IN"
    NOT_IN = "NOT_IN"
    CONTAINS = "CONTAINS"
    STARTS_WITH = "STARTS_WITH"


class SourcingRule(Base):
    """
    A configurable rule that maps order conditions to a sourcing strategy.
    Rules are evaluated in priority order (lower number = higher priority).
    """
    __tablename__ = "sourcing_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    priority = Column(Integer, default=100, nullable=False)  # Lower = higher priority
    is_active = Column(Boolean, default=True)

    # Strategy to apply when this rule matches
    strategy = Column(SAEnum(SourcingStrategy), nullable=False)

    # Conditions (JSON array of condition objects)
    # Each condition: {"field": "channel", "operator": "EQUALS", "value": "WEB"}
    conditions = Column(JSON, default=list)

    # Node filters (which nodes to consider)
    allowed_node_types = Column(JSON, default=list)   # e.g. ["DISTRIBUTION_CENTER"]
    excluded_node_ids = Column(JSON, default=list)    # node UUIDs to exclude
    required_capabilities = Column(JSON, default=list) # e.g. ["can_ship", "can_same_day"]

    # Strategy parameters
    max_split_nodes = Column(Integer, default=3)
    max_distance_km = Column(Float)  # max distance from customer for DISTANCE_OPTIMAL
    cost_weight = Column(Float, default=0.5)      # for COST_OPTIMAL scoring
    distance_weight = Column(Float, default=0.5)  # for hybrid scoring

    # Metadata
    created_by = Column(String(100), default="system")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_sourcing_rules_priority", "priority", "is_active"),
    )
