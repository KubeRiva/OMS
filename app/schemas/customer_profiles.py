"""Pydantic v2 schemas for B2C customer profiles and their saved addresses."""
from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


# ── Address schemas ───────────────────────────────────────────────────────────

class CustomerProfileAddressCreate(BaseModel):
    label: Optional[str] = Field(None, max_length=100)
    is_default: bool = False
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    address1: str = Field(..., max_length=255)
    address2: Optional[str] = Field(None, max_length=255)
    city: str = Field(..., max_length=100)
    state: Optional[str] = Field(None, max_length=100)
    postal_code: str = Field(..., max_length=20)
    country: str = Field(default="US", max_length=3)
    phone: Optional[str] = Field(None, max_length=30)


class CustomerProfileAddressUpdate(BaseModel):
    label: Optional[str] = Field(None, max_length=100)
    is_default: Optional[bool] = None
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    address1: Optional[str] = Field(None, max_length=255)
    address2: Optional[str] = Field(None, max_length=255)
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=100)
    postal_code: Optional[str] = Field(None, max_length=20)
    country: Optional[str] = Field(None, max_length=3)
    phone: Optional[str] = Field(None, max_length=30)


class CustomerProfileAddressResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_id: UUID
    label: Optional[str] = None
    is_default: bool
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    address1: str
    address2: Optional[str] = None
    city: str
    state: Optional[str] = None
    postal_code: str
    country: str
    phone: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ── Profile schemas ───────────────────────────────────────────────────────────

class CustomerProfileCreate(BaseModel):
    email: EmailStr
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=30)
    brand_id: Optional[UUID] = None
    tags: List[str] = Field(default_factory=list)
    email_opt_in: bool = True
    sms_opt_in: bool = False
    preferred_language: str = Field(default="en", max_length=10)
    notes: Optional[str] = None


class CustomerProfileUpdate(BaseModel):
    # email is intentionally absent — it is immutable after creation
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=30)
    tags: Optional[List[str]] = None
    email_opt_in: Optional[bool] = None
    sms_opt_in: Optional[bool] = None
    preferred_language: Optional[str] = Field(None, max_length=10)
    is_active: Optional[bool] = None
    notes: Optional[str] = None
    metadata: Optional[dict] = None


class CustomerProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    brand_id: Optional[UUID] = None
    tags: List[str] = Field(default_factory=list)
    email_opt_in: bool
    sms_opt_in: bool
    preferred_language: str
    total_orders: int
    total_spent: float
    last_order_at: Optional[datetime] = None
    is_active: bool
    notes: Optional[str] = None
    # The ORM attribute is metadata_ (column alias); expose it as `metadata` in the API.
    metadata: Optional[dict] = None
    addresses: List[CustomerProfileAddressResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, v: Any) -> Any:
        """Coerce ORM objects: map metadata_ → metadata, fix tags/total_spent."""
        if isinstance(v, dict):
            return v
        d: dict = {}
        for attr in (
            "id", "email", "first_name", "last_name", "phone", "brand_id",
            "tags", "email_opt_in", "sms_opt_in", "preferred_language",
            "total_orders", "total_spent", "last_order_at", "is_active",
            "notes", "addresses", "created_at", "updated_at",
        ):
            d[attr] = getattr(v, attr, None)
        # metadata_ is the Python attribute name (column is "metadata")
        d["metadata"] = getattr(v, "metadata_", None)
        # Normalise tags
        if not d["tags"]:
            d["tags"] = []
        # Coerce Decimal → float
        if d["total_spent"] is not None and hasattr(d["total_spent"], "__float__"):
            d["total_spent"] = float(d["total_spent"])
        return d


class CustomerProfileListResponse(BaseModel):
    items: List[CustomerProfileResponse]
    total: int
