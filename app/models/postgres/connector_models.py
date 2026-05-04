"""Connector models: integrations with external platforms (Shopify, WooCommerce, etc.)."""
import uuid
import enum
from sqlalchemy import (
    Column, String, DateTime, Integer,
    Enum as SAEnum, Text, ForeignKey, Index, JSON, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.postgres import Base


class ConnectorType(str, enum.Enum):
    SHOPIFY = "SHOPIFY"
    WOOCOMMERCE = "WOOCOMMERCE"
    AMAZON_SP = "AMAZON_SP"
    MAGENTO = "MAGENTO"
    BIGCOMMERCE = "BIGCOMMERCE"
    FEDEX = "FEDEX"
    UPS = "UPS"
    DHL = "DHL"
    CUSTOM = "CUSTOM"


class ConnectorDirection(str, enum.Enum):
    INBOUND = "INBOUND"           # Only receives orders from external
    OUTBOUND = "OUTBOUND"         # Only sends updates to external
    BIDIRECTIONAL = "BIDIRECTIONAL"  # Both directions


class ConnectorStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ERROR = "ERROR"


class Connector(Base):
    __tablename__ = "connectors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    connector_type = Column(SAEnum(ConnectorType), nullable=False)
    direction = Column(SAEnum(ConnectorDirection), nullable=False, default=ConnectorDirection.BIDIRECTIONAL)
    status = Column(SAEnum(ConnectorStatus), nullable=False, default=ConnectorStatus.INACTIVE)

    # Type-specific credentials and settings (stored as JSON)
    # Sensitive fields are masked when returned via API
    config = Column(JSON, default=dict)

    # Sync statistics
    orders_received = Column(Integer, default=0)  # inbound
    orders_synced = Column(Integer, default=0)    # outbound

    # Error tracking
    last_error = Column(Text)
    last_error_at = Column(DateTime(timezone=True))
    last_synced_at = Column(DateTime(timezone=True))

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    events = relationship("ConnectorEvent", back_populates="connector", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_connectors_type_status", "connector_type", "status"),
    )


class ConnectorEvent(Base):
    """Audit log of every inbound/outbound connector activity."""
    __tablename__ = "connector_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connector_id = Column(UUID(as_uuid=True), ForeignKey("connectors.id"), nullable=False)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    external_order_id = Column(String(200))

    # e.g. "order.received", "fulfillment.pushed", "webhook.error"
    event_type = Column(String(100), nullable=False)
    direction = Column(String(20), nullable=False)   # "inbound" | "outbound"
    status = Column(String(20), nullable=False)       # "success" | "failed"

    payload = Column(JSON)         # raw data received / sent
    response = Column(JSON)        # response from external system
    error_message = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    connector = relationship("Connector", back_populates="events")

    __table_args__ = (
        Index("ix_connector_events_connector_created", "connector_id", "created_at"),
        Index("ix_connector_events_order_id", "order_id"),
    )


class ConnectorInventoryMapping(Base):
    """
    Maps one OMS InventoryItem to its platform-specific IDs for a given connector.
    One row per (connector, inventory_item) pair.
    Allows inventory updates to be pushed back to the source platform after stock changes.
    """
    __tablename__ = "connector_inventory_mappings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connector_id = Column(
        UUID(as_uuid=True), ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False
    )
    inventory_item_id = Column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False
    )
    sku = Column(String(100), nullable=False, index=True)

    # Shopify-specific IDs
    shopify_inventory_item_id = Column(String(100))   # variant.inventory_item_id
    shopify_location_id = Column(String(100))          # store's primary location ID

    # Amazon-specific IDs
    amazon_asin = Column(String(20))
    amazon_fnsku = Column(String(20))   # FBA fulfillment network SKU

    # Generic: SKU as known on the external platform (may differ from OMS SKU)
    platform_sku = Column(String(200))
    extra = Column(JSON, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("connector_id", "inventory_item_id", name="uq_connector_inventory_mapping"),
        Index("ix_cim_connector_sku", "connector_id", "sku"),
    )
