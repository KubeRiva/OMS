"""B2B customer account models — credit, payment terms, pricing tiers, contacts, addresses."""
import uuid
import enum
from datetime import datetime

from sqlalchemy import (
    Column, String, Float, Boolean, DateTime, Numeric,
    Enum as SAEnum, Text, ForeignKey, Index, JSON, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.postgres import Base


class AccountType(str, enum.Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ON_HOLD = "ON_HOLD"


class PricingTier(str, enum.Enum):
    STANDARD = "STANDARD"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class PaymentTerms(str, enum.Enum):
    PREPAID = "PREPAID"
    NET_15 = "NET_15"
    NET_30 = "NET_30"
    NET_60 = "NET_60"
    NET_90 = "NET_90"
    COD = "COD"
    UPON_RECEIPT = "UPON_RECEIPT"


class ContactRole(str, enum.Enum):
    PRIMARY = "PRIMARY"
    BILLING = "BILLING"
    SHIPPING = "SHIPPING"
    TECHNICAL = "TECHNICAL"
    OTHER = "OTHER"


class AddressType(str, enum.Enum):
    BILLING = "BILLING"
    SHIPPING = "SHIPPING"
    BOTH = "BOTH"


class CustomerAccount(Base):
    """B2B customer account — a company that places orders on credit/contract terms."""
    __tablename__ = "customer_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_number = Column(String(50), nullable=False, index=True)

    # Identity
    company_name = Column(String(300), nullable=False, index=True)
    trading_name = Column(String(300))
    industry = Column(String(100))
    website = Column(String(300))
    account_type = Column(SAEnum(AccountType), default=AccountType.PROSPECT, nullable=False)

    # Primary contact
    contact_name = Column(String(200))
    contact_email = Column(String(255), index=True)
    contact_phone = Column(String(30))

    # Credit & payment
    credit_limit = Column(Numeric(14, 2), default=0)
    credit_used = Column(Numeric(14, 2), default=0)       # updated on invoice creation
    payment_terms = Column(String(20), default="PREPAID")  # mirrors PaymentTerms enum
    pricing_tier = Column(SAEnum(PricingTier), default=PricingTier.STANDARD, nullable=False)

    # Tax
    tax_exempt = Column(Boolean, default=False)
    tax_exempt_id = Column(String(100))

    # Billing address
    billing_name = Column(String(200))
    billing_address1 = Column(String(255))
    billing_address2 = Column(String(255))
    billing_city = Column(String(100))
    billing_state = Column(String(100))
    billing_postal_code = Column(String(20))
    billing_country = Column(String(3), default="US")

    # Account manager (internal OMS user)
    account_manager_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Brand association
    brand_id = Column(UUID(as_uuid=True), ForeignKey("brands.id"), nullable=True)

    # Hierarchy — parent account for subsidiaries/divisions
    parent_account_id = Column(UUID(as_uuid=True), ForeignKey("customer_accounts.id"), nullable=True)

    # Approval threshold — orders above this value require approval
    approval_threshold = Column(Numeric(14, 2), nullable=True)

    notes = Column(Text)
    metadata_ = Column("metadata", JSON, default=dict)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    orders = relationship("Order", back_populates="customer_account", lazy="select")
    brand = relationship("Brand", back_populates="customer_accounts", lazy="select")
    account_manager = relationship("User", foreign_keys=[account_manager_id])
    child_accounts = relationship("CustomerAccount", foreign_keys=[parent_account_id])
    contacts = relationship(
        "AccountContact",
        back_populates="customer_account",
        cascade="all, delete-orphan",
        lazy="select",
    )
    addresses = relationship(
        "AccountAddress",
        back_populates="customer_account",
        cascade="all, delete-orphan",
        lazy="select",
    )

    @property
    def available_credit(self) -> float:
        limit = float(self.credit_limit or 0)
        used = float(self.credit_used or 0)
        return max(0.0, limit - used)

    __table_args__ = (
        UniqueConstraint("account_number", name="uq_account_number"),
        Index("ix_customer_accounts_type_active", "account_type", "is_active"),
        Index("ix_customer_accounts_manager", "account_manager_id"),
    )


class AccountContact(Base):
    """A named contact person associated with a B2B customer account."""
    __tablename__ = "account_contacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("customer_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(SAEnum(ContactRole), default=ContactRole.OTHER, nullable=False)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(30), nullable=True)
    title = Column(String(100), nullable=True)
    is_primary = Column(Boolean, default=False, nullable=False)
    receives_invoices = Column(Boolean, default=False, nullable=False)
    receives_order_updates = Column(Boolean, default=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    customer_account = relationship("CustomerAccount", back_populates="contacts")


class AccountAddress(Base):
    """A ship-to or bill-to address associated with a B2B customer account."""
    __tablename__ = "account_addresses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("customer_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    address_type = Column(SAEnum(AddressType), default=AddressType.SHIPPING, nullable=False)
    label = Column(String(100), nullable=True)  # e.g. "DC East", "Store #42"

    address1 = Column(String(255), nullable=False)
    address2 = Column(String(255), nullable=True)
    city = Column(String(100), nullable=False)
    state = Column(String(100), nullable=True)
    postal_code = Column(String(20), nullable=False)
    country = Column(String(3), default="US", nullable=False)

    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    is_default = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    customer_account = relationship("CustomerAccount", back_populates="addresses")
