from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime
from uuid import UUID
from app.models.postgres.sourcing_rule_models import SourcingStrategy, ConditionOperator


class SourcingCondition(BaseModel):
    field: str
    operator: ConditionOperator
    value: Any


class SourcingTarget(BaseModel):
    """A single resolved target for a sourcing rule — either a DG or a direct node."""
    type: str        # "DISTRIBUTION_GROUP" | "NODE"
    id: str          # UUID of the DG or Node
    priority: int = 1


# ─── Distribution Group schemas ──────────────────────────────────────────────

class DGMemberCreate(BaseModel):
    node_id: str
    priority: int = Field(default=1, ge=1)


class DGMemberResponse(BaseModel):
    id: UUID
    group_id: UUID
    node_id: UUID
    priority: int
    node_name: Optional[str] = None
    node_code: Optional[str] = None
    node_type: Optional[str] = None
    model_config = {"from_attributes": True}


class DistributionGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    is_active: bool = True
    brand_id: Optional[str] = None
    members: List[DGMemberCreate] = Field(default_factory=list)


class DistributionGroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    brand_id: Optional[str] = None


class DistributionGroupResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    is_active: bool
    brand_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    members: List[DGMemberResponse] = []
    model_config = {"from_attributes": True}


class DistributionGroupListResponse(BaseModel):
    items: List[DistributionGroupResponse]
    total: int


# ─── Sourcing Rule schemas ────────────────────────────────────────────────────

class SourcingRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    priority: int = Field(default=100, ge=1)
    is_active: bool = True
    strategy: SourcingStrategy
    conditions: List[SourcingCondition] = Field(default_factory=list)
    sourcing_targets: List[SourcingTarget] = Field(default_factory=list)
    allowed_node_types: List[str] = Field(default_factory=list)
    excluded_node_ids: List[str] = Field(default_factory=list)
    required_capabilities: List[str] = Field(default_factory=list)
    max_split_nodes: int = Field(default=3, ge=1, le=10)
    max_distance_km: Optional[float] = None
    cost_weight: float = Field(default=0.5, ge=0, le=1)
    distance_weight: float = Field(default=0.5, ge=0, le=1)
    created_by: str = "system"


class SourcingRuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None
    strategy: Optional[SourcingStrategy] = None
    conditions: Optional[List[SourcingCondition]] = None
    sourcing_targets: Optional[List[SourcingTarget]] = None
    allowed_node_types: Optional[List[str]] = None
    excluded_node_ids: Optional[List[str]] = None
    required_capabilities: Optional[List[str]] = None
    max_split_nodes: Optional[int] = None
    max_distance_km: Optional[float] = None
    cost_weight: Optional[float] = None
    distance_weight: Optional[float] = None


class SourcingRuleResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    priority: int
    is_active: bool
    strategy: SourcingStrategy
    conditions: list
    sourcing_targets: list = []
    allowed_node_types: list
    excluded_node_ids: list
    required_capabilities: list
    max_split_nodes: int
    max_distance_km: Optional[float] = None
    cost_weight: float
    distance_weight: float
    brand_id: Optional[UUID] = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class SourcingRuleListResponse(BaseModel):
    items: List[SourcingRuleResponse]
    total: int


class SourcingRequest(BaseModel):
    order_id: UUID
    force_strategy: Optional[SourcingStrategy] = None


class SourcingResult(BaseModel):
    order_id: UUID
    rule_applied: Optional[str] = None
    strategy_used: SourcingStrategy
    allocations: List[dict]
    total_split_nodes: int
    sourcing_score: float
    processing_time_ms: float
    rule_details: Optional[dict] = None
    candidates_evaluated: List[dict] = []
    experiment_id: Optional[str] = None
