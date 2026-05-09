"""Brand entity — logical brand within an environment (B2C vs B2B)."""
import uuid
import enum

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint,
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.postgres import Base


class BrandTenantMode(str, enum.Enum):
    B2C_ONLY = "B2C_ONLY"
    B2B_ONLY = "B2B_ONLY"
    HYBRID   = "HYBRID"


class InventoryMode(str, enum.Enum):
    SHARED   = "SHARED"    # brand draws from global node inventory pool
    ISOLATED = "ISOLATED"  # brand owns its own stock (brand_id tagged on InventoryItem)


class Brand(Base):
    __tablename__ = "brands"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug        = Column(String(80), unique=True, nullable=False, index=True)
    name        = Column(String(200), nullable=False)
    tenant_mode = Column(SAEnum(BrandTenantMode), nullable=False, default=BrandTenantMode.HYBRID)
    description = Column(Text, nullable=True)
    is_active   = Column(Boolean, default=True, nullable=False)
    inventory_mode = Column(
        String(20), nullable=False, default=InventoryMode.SHARED.value
    )
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships (back-populated from child tables)
    # foreign_keys required because Order now has two FKs to brands (brand_id + seller_brand_id)
    orders            = relationship("Order",           back_populates="brand",   lazy="dynamic",
                                     foreign_keys="Order.brand_id")
    seller_orders     = relationship("Order",           back_populates="seller_brand", lazy="dynamic",
                                     foreign_keys="Order.seller_brand_id")
    sourcing_rules    = relationship("SourcingRule",    back_populates="brand",   lazy="dynamic")
    customer_accounts = relationship("CustomerAccount", back_populates="brand",   lazy="dynamic")
    connectors        = relationship("Connector",       back_populates="brand",   lazy="dynamic")

    # Phase 2/3/5 relationships
    config = relationship(
        "BrandConfig",
        back_populates="brand",
        uselist=False,
        cascade="all, delete-orphan",
    )
    brand_nodes = relationship(
        "BrandNode",
        back_populates="brand",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_brands_active", "is_active"),
    )


class BrandConfig(Base):
    """
    Per-brand operational configuration.

    ai_sourcing_enabled=True means the AI_ADAPTIVE and AI_HYBRID sourcing strategies
    are available for this brand. New brands start with no sourcing patterns — the AI
    falls back to DISTANCE_OPTIMAL automatically (MIN_CLUSTER_SAMPLES=50 threshold
    already in place). This graceful degradation is the correct behavior for new
    brand onboarding.
    """
    __tablename__ = "brand_configs"

    id      = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(
        UUID(as_uuid=True),
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Localisation
    default_currency = Column(String(3),  nullable=False, default="USD")
    default_locale   = Column(String(10), nullable=False, default="en-US")

    # SLA / policy
    sla_ship_hours     = Column(Integer, nullable=False, default=48)
    sla_deliver_days   = Column(Integer, nullable=False, default=5)
    return_window_days = Column(Integer, nullable=False, default=30)

    # Branding / support
    logo_url      = Column(Text,         nullable=True)
    support_email = Column(String(255),  nullable=True)
    support_phone = Column(String(50),   nullable=True)

    # Operational defaults
    default_fulfillment_type = Column(String(50), nullable=True)

    # AI-native flags
    auto_approve_orders  = Column(Boolean, nullable=False, default=False)
    # auto_approve_orders: AI-native — auto-approve B2B orders below threshold
    ai_sourcing_enabled  = Column(Boolean, nullable=False, default=True)
    # ai_sourcing_enabled: enable AI_ADAPTIVE/AI_HYBRID strategies for this brand

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationship
    brand = relationship("Brand", back_populates="config")


class BrandNode(Base):
    """Maps a fulfillment node to a brand with brand-specific priority and caps."""
    __tablename__ = "brand_nodes"

    id       = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id = Column(
        UUID(as_uuid=True),
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_id  = Column(
        UUID(as_uuid=True),
        ForeignKey("fulfillment_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    priority         = Column(Integer, nullable=False, default=100)  # lower = higher priority
    is_active        = Column(Boolean, nullable=False, default=True)
    max_daily_orders = Column(Integer, nullable=True)  # brand-specific cap at this node
    created_at       = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    brand = relationship("Brand", back_populates="brand_nodes")
    node  = relationship("FulfillmentNode")

    __table_args__ = (
        UniqueConstraint("brand_id", "node_id", name="uq_brand_nodes_brand_node"),
        Index("ix_brand_nodes_brand", "brand_id"),
    )
