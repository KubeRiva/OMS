"""B2C customer profile models — lightweight profiles linked to order history."""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, Integer,
    JSON, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.postgres import Base


class CustomerProfile(Base):
    """A B2C customer profile — enriches the bare email string stored on orders."""
    __tablename__ = "customer_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), nullable=False, index=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    phone = Column(String(30), nullable=True)

    # Optional brand scoping (nullable = profile applies to all brands)
    brand_id = Column(UUID(as_uuid=True), ForeignKey("brands.id"), nullable=True, index=True)

    # Tags / segments for marketing (list of strings stored as JSON)
    tags = Column(JSON, default=list)

    # Communication preferences
    email_opt_in = Column(Boolean, default=True, nullable=False)
    sms_opt_in = Column(Boolean, default=False, nullable=False)
    preferred_language = Column(String(10), default="en", nullable=False)

    # Lifetime stats — denormalized, updated via sync-stats endpoint
    total_orders = Column(Integer, default=0, nullable=False)
    total_spent = Column(Numeric(14, 2), default=0, nullable=False)
    last_order_at = Column(DateTime(timezone=True), nullable=True)

    # Account status
    is_active = Column(Boolean, default=True, nullable=False)
    notes = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSON, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    brand = relationship("Brand", lazy="select")
    addresses = relationship(
        "CustomerProfileAddress",
        back_populates="customer",
        cascade="all, delete-orphan",
        lazy="select",
    )

    __table_args__ = (
        UniqueConstraint("email", "brand_id", name="uq_customer_email_brand"),
        Index("ix_customer_profiles_email_brand", "email", "brand_id"),
        Index("ix_customer_profiles_brand", "brand_id"),
        Index("ix_customer_profiles_active", "is_active"),
    )


class CustomerProfileAddress(Base):
    """A saved address belonging to a B2C customer profile."""
    __tablename__ = "customer_profile_addresses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("customer_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label = Column(String(100), nullable=True)   # e.g. "Home", "Work"
    is_default = Column(Boolean, default=False, nullable=False)

    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    address1 = Column(String(255), nullable=False)
    address2 = Column(String(255), nullable=True)
    city = Column(String(100), nullable=False)
    state = Column(String(100), nullable=True)
    postal_code = Column(String(20), nullable=False)
    country = Column(String(3), default="US", nullable=False)
    phone = Column(String(30), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    customer = relationship("CustomerProfile", back_populates="addresses")
