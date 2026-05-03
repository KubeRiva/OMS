"""Pydantic schemas for Lifecycle and LifecycleStep."""
from typing import Optional, List, Any
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field


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
    fulfillment_types: List[str] = Field(default_factory=list)
    channels: List[str] = Field(default_factory=list)
    is_active: bool = True
    is_default: bool = False
    created_by: str = "system"
    steps: List[LifecycleStepCreate] = Field(default_factory=list)


class LifecycleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    fulfillment_types: Optional[List[str]] = None
    channels: Optional[List[str]] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None
    steps: Optional[List[LifecycleStepCreate]] = None


class LifecycleResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    fulfillment_types: List[str]
    channels: List[str]
    is_active: bool
    is_default: bool
    created_by: str
    created_at: datetime
    updated_at: datetime
    steps: List[LifecycleStepResponse] = []
    model_config = {"from_attributes": True}


class LifecycleResolveResponse(BaseModel):
    """Result of resolving which lifecycle applies to a given order context."""
    lifecycle: Optional[LifecycleResponse] = None
    matched_on: str  # "exact", "fulfillment_type", "default", "none"
