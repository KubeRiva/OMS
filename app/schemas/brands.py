"""Brand Pydantic schemas."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.postgres.brand_models import BrandTenantMode, InventoryMode


class BrandCreate(BaseModel):
    slug: str = Field(..., min_length=2, max_length=80, pattern=r"^[a-z0-9-]+$")
    name: str = Field(..., min_length=1, max_length=200)
    tenant_mode: BrandTenantMode = BrandTenantMode.HYBRID
    description: Optional[str] = None
    inventory_mode: InventoryMode = InventoryMode.SHARED


class BrandUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    tenant_mode: Optional[BrandTenantMode] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    inventory_mode: Optional[InventoryMode] = None


class BrandSummary(BaseModel):
    """Lightweight reference used as FK in other schemas."""
    id: UUID
    slug: str
    name: str
    tenant_mode: BrandTenantMode
    is_active: bool

    model_config = {"from_attributes": True}


class BrandResponse(BaseModel):
    id: UUID
    slug: str
    name: str
    tenant_mode: BrandTenantMode
    description: Optional[str] = None
    is_active: bool
    inventory_mode: InventoryMode = InventoryMode.SHARED
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Computed counts (populated by the router)
    order_count: int = 0
    rule_count: int = 0
    account_count: int = 0

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# BrandConfig schemas
# ---------------------------------------------------------------------------

class BrandConfigCreate(BaseModel):
    default_currency: str = "USD"
    default_locale: str = "en-US"
    sla_ship_hours: int = 48
    sla_deliver_days: int = 5
    return_window_days: int = 30
    logo_url: Optional[str] = None
    support_email: Optional[str] = None
    support_phone: Optional[str] = None
    default_fulfillment_type: Optional[str] = None
    auto_approve_orders: bool = False
    ai_sourcing_enabled: bool = True


class BrandConfigResponse(BrandConfigCreate):
    id: UUID
    brand_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# BrandNode schemas
# ---------------------------------------------------------------------------

class BrandNodeCreate(BaseModel):
    node_id: UUID
    priority: int = 100
    is_active: bool = True
    max_daily_orders: Optional[int] = None


class BrandNodeResponse(BrandNodeCreate):
    id: UUID
    brand_id: UUID
    node_name: Optional[str] = None   # populated by join
    node_code: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Brand clone request
# ---------------------------------------------------------------------------

class BrandCloneRequest(BaseModel):
    name: str
    slug: str = Field(..., min_length=2, max_length=80, pattern=r"^[a-z0-9-]+$")
    tenant_mode: BrandTenantMode = BrandTenantMode.B2C_ONLY
    clone_config: bool = True        # copy BrandConfig settings
    clone_nodes: bool = True         # copy BrandNode assignments
    clone_sourcing_rules: bool = False  # copy SourcingRules (creates inactive copies)
