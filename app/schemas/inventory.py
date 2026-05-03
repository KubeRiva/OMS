from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID
from app.models.postgres.inventory_models import InventoryAdjustmentReason


class InventoryItemBase(BaseModel):
    node_id: UUID
    sku: str = Field(..., min_length=1, max_length=100)
    product_name: Optional[str] = None
    quantity_on_hand: int = Field(default=0, ge=0)
    reorder_point: int = Field(default=10, ge=0)
    reorder_quantity: int = Field(default=100, ge=1)
    unit_cost: float = Field(default=0.0, ge=0)
    weight_lbs: float = Field(default=0.0, ge=0)


class InventoryItemCreate(InventoryItemBase):
    pass


class InventoryItemUpdate(BaseModel):
    product_name: Optional[str] = None
    reorder_point: Optional[int] = None
    reorder_quantity: Optional[int] = None
    quantity_on_order: Optional[int] = None
    unit_cost: Optional[float] = None
    weight_lbs: Optional[float] = None
    is_active: Optional[bool] = None


class InventoryItemResponse(InventoryItemBase):
    id: UUID
    quantity_reserved: int
    quantity_available: int
    quantity_on_order: int = 0
    is_active: bool = True
    last_counted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InventoryAdjustmentCreate(BaseModel):
    reason: InventoryAdjustmentReason
    quantity_delta: int
    reference_id: Optional[str] = None
    notes: Optional[str] = None
    created_by: str = "system"


class InventoryAdjustmentResponse(BaseModel):
    id: UUID
    inventory_item_id: UUID
    reason: InventoryAdjustmentReason
    quantity_delta: int
    quantity_before: int
    quantity_after: int
    reference_id: Optional[str] = None
    notes: Optional[str] = None
    created_by: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ProductSummary(BaseModel):
    """Aggregated view of all inventory items for a single SKU across nodes."""
    sku: str
    product_name: Optional[str] = None
    total_on_hand: int
    total_available: int
    total_reserved: int
    nodes_count: int
    unit_cost: float
    weight_lbs: float
    reorder_point: int
    updated_at: Optional[datetime] = None


class ProductUpdate(BaseModel):
    """Update product-level attributes across all nodes."""
    product_name: Optional[str] = None
    unit_cost: Optional[float] = None
    weight_lbs: Optional[float] = None
    reorder_point: Optional[int] = None
    reorder_quantity: Optional[int] = None
    is_active: Optional[bool] = None


class BulkInventoryCheck(BaseModel):
    items: list[dict]  # [{"sku": "SKU123", "quantity": 2}, ...]


class InventoryCheckResult(BaseModel):
    sku: str
    requested_quantity: int
    available_by_node: list[dict]
    total_available: int
    fulfillable: bool


class InventoryTransfer(BaseModel):
    from_node_id: UUID
    to_node_id: UUID
    sku: str
    quantity: int = Field(..., ge=1)
    notes: Optional[str] = None
