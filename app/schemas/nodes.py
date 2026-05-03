from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
from uuid import UUID
from app.models.postgres.node_models import NodeType, NodeStatus


class NodeBase(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=200)
    node_type: NodeType
    status: NodeStatus = NodeStatus.ACTIVE
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: str = "US"
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    can_ship: bool = True
    can_pickup: bool = False
    can_curbside: bool = False
    can_same_day: bool = False
    daily_order_capacity: int = Field(default=500, ge=1)
    avg_processing_hours: float = Field(default=24.0, ge=0)
    shipping_cost_multiplier: float = Field(default=1.0, ge=0)


class NodeCreate(NodeBase):
    pass


class NodeUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[NodeStatus] = None
    can_ship: Optional[bool] = None
    can_pickup: Optional[bool] = None
    can_curbside: Optional[bool] = None
    can_same_day: Optional[bool] = None
    daily_order_capacity: Optional[int] = None
    avg_processing_hours: Optional[float] = None
    shipping_cost_multiplier: Optional[float] = None


class NodeResponse(NodeBase):
    id: UUID
    current_daily_orders: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NodeListResponse(BaseModel):
    items: list[NodeResponse]
    total: int
