"""B2B customer account schemas."""
import enum
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from decimal import Decimal

from app.models.postgres.b2b_models import AccountType, PricingTier, PaymentTerms


# ── Contact schemas ───────────────────────────────────────────────────────────

class ContactRole(str, enum.Enum):
    PRIMARY = "PRIMARY"
    BILLING = "BILLING"
    SHIPPING = "SHIPPING"
    TECHNICAL = "TECHNICAL"
    OTHER = "OTHER"


class AccountContactCreate(BaseModel):
    role: ContactRole = ContactRole.OTHER
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    title: Optional[str] = None
    is_primary: bool = False
    receives_invoices: bool = False
    receives_order_updates: bool = True
    notes: Optional[str] = None


class AccountContactUpdate(BaseModel):
    role: Optional[ContactRole] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    title: Optional[str] = None
    is_primary: Optional[bool] = None
    receives_invoices: Optional[bool] = None
    receives_order_updates: Optional[bool] = None
    notes: Optional[str] = None


class AccountContactResponse(BaseModel):
    id: UUID
    customer_account_id: UUID
    role: str
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    title: Optional[str] = None
    is_primary: bool
    receives_invoices: bool
    receives_order_updates: bool
    is_active: bool
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Address schemas ───────────────────────────────────────────────────────────

class AddressType(str, enum.Enum):
    BILLING = "BILLING"
    SHIPPING = "SHIPPING"
    BOTH = "BOTH"


class AccountAddressCreate(BaseModel):
    address_type: AddressType = AddressType.SHIPPING
    label: Optional[str] = None
    address1: str
    address2: Optional[str] = None
    city: str
    state: Optional[str] = None
    postal_code: str
    country: str = "US"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_default: bool = False


class AccountAddressUpdate(BaseModel):
    address_type: Optional[AddressType] = None
    label: Optional[str] = None
    address1: Optional[str] = None
    address2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_default: Optional[bool] = None


class AccountAddressResponse(BaseModel):
    id: UUID
    customer_account_id: UUID
    address_type: str
    label: Optional[str] = None
    address1: str
    address2: Optional[str] = None
    city: str
    state: Optional[str] = None
    postal_code: str
    country: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Customer account schemas ──────────────────────────────────────────────────

class CustomerAccountCreate(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=300)
    trading_name: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    account_type: AccountType = AccountType.PROSPECT

    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None

    credit_limit: Decimal = Field(default=Decimal("0.00"), ge=0, le=Decimal("10000000"))
    payment_terms: PaymentTerms = PaymentTerms.PREPAID
    pricing_tier: PricingTier = PricingTier.STANDARD

    tax_exempt: bool = False
    tax_exempt_id: Optional[str] = None

    billing_name: Optional[str] = None
    billing_address1: Optional[str] = None
    billing_address2: Optional[str] = None
    billing_city: Optional[str] = None
    billing_state: Optional[str] = None
    billing_postal_code: Optional[str] = None
    billing_country: str = "US"

    account_manager_id: Optional[UUID] = None
    parent_account_id: Optional[UUID] = None
    approval_threshold: Optional[Decimal] = Field(default=None, ge=0)

    notes: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class CustomerAccountUpdate(BaseModel):
    company_name: Optional[str] = None
    trading_name: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    account_type: Optional[AccountType] = None

    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None

    credit_limit: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("10000000"))
    payment_terms: Optional[PaymentTerms] = None
    pricing_tier: Optional[PricingTier] = None

    tax_exempt: Optional[bool] = None
    tax_exempt_id: Optional[str] = None

    billing_name: Optional[str] = None
    billing_address1: Optional[str] = None
    billing_address2: Optional[str] = None
    billing_city: Optional[str] = None
    billing_state: Optional[str] = None
    billing_postal_code: Optional[str] = None
    billing_country: Optional[str] = None

    account_manager_id: Optional[UUID] = None
    parent_account_id: Optional[UUID] = None
    approval_threshold: Optional[Decimal] = Field(default=None, ge=0)
    is_active: Optional[bool] = None

    notes: Optional[str] = None
    metadata: Optional[dict] = None


class CustomerAccountResponse(BaseModel):
    id: UUID
    account_number: str
    company_name: str
    trading_name: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    account_type: AccountType
    pricing_tier: PricingTier
    payment_terms: str

    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None

    credit_limit: Decimal
    credit_used: Decimal
    available_credit: float

    tax_exempt: bool
    tax_exempt_id: Optional[str] = None

    billing_name: Optional[str] = None
    billing_address1: Optional[str] = None
    billing_address2: Optional[str] = None
    billing_city: Optional[str] = None
    billing_state: Optional[str] = None
    billing_postal_code: Optional[str] = None
    billing_country: Optional[str] = None

    account_manager_id: Optional[UUID] = None
    parent_account_id: Optional[UUID] = None
    approval_threshold: Optional[Decimal] = None

    is_active: bool
    notes: Optional[str] = None
    metadata: dict = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime

    contacts: List[AccountContactResponse] = Field(default_factory=list)
    addresses: List[AccountAddressResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True, "populate_by_name": True}


class CustomerAccountListResponse(BaseModel):
    items: List[CustomerAccountResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class CreditAdjustment(BaseModel):
    """Manually adjust credit_used — e.g. after invoice payment."""
    amount: Decimal = Field(
        ...,
        ge=Decimal("-1000000"),
        le=Decimal("1000000"),
        description="Positive = increase used credit, Negative = release credit",
    )
    reason: str = Field(..., min_length=10)
