"""Pydantic schemas for Lifecycle and LifecycleStep."""
from typing import Optional, List, Any
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field


class CustomStatusDef(BaseModel):
    key: str = Field(..., min_length=1, max_length=50, pattern=r'^[A-Z0-9_]+$')
    label: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    color: str = "#6b7280"   # tailwind-compatible hex


class LifecycleStepCreate(BaseModel):
    status: str
    label: str
    description: str = ""
    step_order: int = 0
    allowed_next_statuses: List[str] = Field(default_factory=list)
    action_type: Optional[str] = None
    sla_hours: Optional[float] = None


class LifecycleStepResponse(LifecycleStepCreate):
    id: UUID
    lifecycle_id: UUID
    model_config = {"from_attributes": True}


class LifecycleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    pipeline_type: str = "ORDER"         # "ORDER" | "RETURN"
    fulfillment_types: List[str] = Field(default_factory=list)
    channels: List[str] = Field(default_factory=list)
    order_type: Optional[str] = None     # "RETAIL" | "B2B" | "WHOLESALE" | null
    brand_id: Optional[str] = None
    custom_statuses: List[CustomStatusDef] = Field(default_factory=list)
    is_active: bool = True
    is_default: bool = False
    created_by: str = "system"
    steps: List[LifecycleStepCreate] = Field(default_factory=list)


class LifecycleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    pipeline_type: Optional[str] = None
    fulfillment_types: Optional[List[str]] = None
    channels: Optional[List[str]] = None
    order_type: Optional[str] = None
    brand_id: Optional[str] = None
    custom_statuses: Optional[List[CustomStatusDef]] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None
    steps: Optional[List[LifecycleStepCreate]] = None


class LifecycleResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    pipeline_type: str
    fulfillment_types: List[str]
    channels: List[str]
    order_type: Optional[str] = None
    brand_id: Optional[UUID] = None
    custom_statuses: List[dict] = []
    is_active: bool
    is_default: bool
    created_by: str
    created_at: datetime
    updated_at: datetime
    steps: List[LifecycleStepResponse] = []
    model_config = {"from_attributes": True}


class LifecycleResolveResponse(BaseModel):
    lifecycle: Optional[LifecycleResponse] = None
    matched_on: str
