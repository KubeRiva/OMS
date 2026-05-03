"""
AI platform models: proposals, custom attributes, UI widgets, experiments, outcome labels.
All changes made via these models are additive-only — no DROP, no destructive ALTER.
"""
import uuid
import enum

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text, JSON,
    Enum as SAEnum, ForeignKey, Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database.postgres import Base


class ProposalType(str, enum.Enum):
    SOURCING_RULE = "sourcing_rule"
    CUSTOM_ATTRIBUTE = "custom_attribute"
    SCHEMA_MIGRATION = "schema_migration"
    UI_WIDGET = "ui_widget"
    CONFIG_CHANGE = "config_change"
    SOURCING_EXPERIMENT = "sourcing_experiment"


class ProposalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"


class AIProposal(Base):
    """
    All AI-proposed changes await human review here before any application.
    Safety guarantee: nothing is applied without approved_by + explicit apply call.
    """
    __tablename__ = "ai_proposals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proposal_type = Column(SAEnum(ProposalType), nullable=False)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    rationale = Column(Text)               # Data-backed reason for the proposal
    confidence_score = Column(Float, default=0.0)  # 0-1
    proposal_data = Column(JSON, nullable=False)   # Change payload
    status = Column(SAEnum(ProposalStatus), default=ProposalStatus.PENDING, nullable=False)
    generated_by = Column(String(100))     # AI session/chat ID or 'learning_worker'
    approved_by = Column(String(200))      # Admin email
    applied_at = Column(DateTime(timezone=True))
    rollback_data = Column(JSON)           # Data needed to undo the change
    rejection_reason = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_ai_proposals_status", "status", "created_at"),
        Index("ix_ai_proposals_type", "proposal_type", "status"),
    )


class AttributeDataType(str, enum.Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ENUM = "enum"
    DATE = "date"


class CustomAttributeDefinition(Base):
    """
    Defines dynamic schema extensions stored in entity metadata_ JSONB fields.
    Zero schema risk: uses existing JSONB columns, no DDL required.
    """
    __tablename__ = "custom_attribute_definitions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type = Column(String(50), nullable=False)   # 'order', 'order_item', 'product', 'node'
    attribute_key = Column(String(100), nullable=False)
    attribute_label = Column(String(200), nullable=False)
    data_type = Column(SAEnum(AttributeDataType), nullable=False)
    enum_values = Column(JSON)             # For enum type: ["VIP", "STANDARD", "TRIAL"]
    is_required = Column(Boolean, default=False)
    default_value = Column(JSON)
    is_searchable = Column(Boolean, default=False)
    display_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_by = Column(String(200))       # Admin email or 'AI'
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_custom_attrs_entity", "entity_type", "is_active"),
        Index("ix_custom_attrs_key", "entity_type", "attribute_key", unique=True),
    )


class WidgetType(str, enum.Enum):
    METRIC_CARD = "metric_card"
    TIME_SERIES = "time_series"
    BAR_CHART = "bar_chart"
    TABLE = "table"
    DISTRIBUTION = "distribution"


class UIWidget(Base):
    """
    JSON-configured dashboard widgets. AI proposes JSON configs; no arbitrary code generated.
    """
    __tablename__ = "ui_widgets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    widget_key = Column(String(100), unique=True, nullable=False)
    title = Column(String(200), nullable=False)
    widget_type = Column(SAEnum(WidgetType), nullable=False)
    page_target = Column(String(100), default="dashboard")  # 'dashboard', 'analytics', 'architect'
    config = Column(JSON, nullable=False)  # Widget-type-specific config
    display_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_by = Column(String(200))
    proposal_id = Column(UUID(as_uuid=True), ForeignKey("ai_proposals.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_ui_widgets_page", "page_target", "is_active", "display_order"),
    )


class ExperimentStatus(str, enum.Enum):
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"


class AIExperiment(Base):
    """
    A/B tests comparing sourcing strategies. Traffic split is additive —
    both strategies remain operational at all times.
    """
    __tablename__ = "ai_experiments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    strategy_a = Column(String(50), nullable=False)   # e.g. 'DISTANCE_OPTIMAL'
    strategy_b = Column(String(50), nullable=False)   # e.g. 'AI_ADAPTIVE'
    traffic_split_pct = Column(Float, default=10.0)   # % sent to strategy_b (0-100)
    filter_conditions = Column(JSON, default=dict)    # Which orders qualify
    status = Column(SAEnum(ExperimentStatus), default=ExperimentStatus.RUNNING, nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True))
    winner = Column(String(50))            # Determined at end
    results = Column(JSON)                 # Computed outcome comparison
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_ai_experiments_status", "status", "started_at"),
    )


class SourcingOutcomeLabel(Base):
    """
    PostgreSQL mirror of MongoDB sourcing_outcomes for fast analytical queries.
    Written by the learning worker after outcome data is available.
    """
    __tablename__ = "sourcing_outcome_labels"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    allocation_id = Column(UUID(as_uuid=True), ForeignKey("fulfillment_allocations.id"), nullable=True)
    strategy_used = Column(String(50))
    experiment_id = Column(UUID(as_uuid=True), ForeignKey("ai_experiments.id"), nullable=True)
    outcome_score = Column(Float)          # 0-1 computed quality
    delivery_hours_actual = Column(Float)
    cost_variance_pct = Column(Float)
    was_backordered = Column(Boolean, default=False)
    was_returned = Column(Boolean, default=False)
    labeled_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_outcome_labels_order", "order_id"),
        Index("ix_outcome_labels_strategy", "strategy_used", "labeled_at"),
        Index("ix_outcome_labels_score", "outcome_score", "labeled_at"),
    )
