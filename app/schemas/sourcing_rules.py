from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime
from uuid import UUID
from app.models.postgres.sourcing_rule_models import SourcingStrategy, ConditionOperator


class SourcingCondition(BaseModel):
    field: str  # e.g. "channel", "fulfillment_type", "total_amount"
    operator: ConditionOperator
    value: Any  # string, number, or list for IN/NOT_IN


class SourcingRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    priority: int = Field(default=100, ge=1)
    is_active: bool = True
    strategy: SourcingStrategy
    conditions: List[SourcingCondition] = Field(default_factory=list)
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
    allowed_node_types: list
    excluded_node_ids: list
    required_capabilities: list
    max_split_nodes: int
    max_distance_km: Optional[float] = None
    cost_weight: float
    distance_weight: float
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SourcingRuleListResponse(BaseModel):
    items: List[SourcingRuleResponse]
    total: int


class SourcingRequest(BaseModel):
    """Manual sourcing evaluation request."""
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
    # Decision trail fields
    rule_details: Optional[dict] = None          # full rule info that was matched
    candidates_evaluated: List[dict] = []        # all nodes considered with scores
    # A/B experiment tracking
    experiment_id: Optional[str] = None          # set if order was routed by an experiment
