"""
Architect router — AI Architect control center (superadmin only).

Endpoints:
  GET    /architect/proposals                   — list proposals (filterable)
  GET    /architect/proposals/{id}              — proposal detail
  POST   /architect/proposals/{id}/approve      — mark approved
  POST   /architect/proposals/{id}/reject       — mark rejected with reason
  POST   /architect/proposals/{id}/apply        — execute approved proposal
  POST   /architect/proposals/{id}/rollback     — undo applied proposal
  GET    /architect/patterns                    — discovered sourcing patterns (MongoDB)
  GET    /architect/node-performance            — rolling node metrics (MongoDB)
  GET    /architect/ai-sourcing/performance     — AI vs rule-based comparison (MongoDB)
  GET    /architect/experiments                 — list A/B experiments
  POST   /architect/experiments                 — create a new experiment
  POST   /architect/experiments/{id}/pause      — pause a running experiment
  POST   /architect/experiments/{id}/resume     — resume a paused experiment
  GET    /architect/experiments/{id}/results    — current arm comparison from MongoDB
"""
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.postgres import get_db
from app.database.mongodb import get_mongo_ai_db
from app.dependencies.auth import require_superadmin
from app.models.postgres.ai_models import AIProposal, ProposalType, ProposalStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/architect", tags=["Architect"])


# ─── Pydantic Schemas ─────────────────────────────────────────────────────────

class ProposalResponse(BaseModel):
    id: str
    proposal_type: str
    title: str
    description: Optional[str]
    rationale: Optional[str]
    confidence_score: float
    status: str
    generated_by: Optional[str]
    approved_by: Optional[str]
    applied_at: Optional[datetime]
    rejection_reason: Optional[str]
    proposal_data: Optional[dict]
    rollback_data: Optional[dict]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RejectRequest(BaseModel):
    reason: str


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _proposal_to_response(p: AIProposal) -> ProposalResponse:
    return ProposalResponse(
        id=str(p.id),
        proposal_type=p.proposal_type.value,
        title=p.title,
        description=p.description,
        rationale=p.rationale,
        confidence_score=p.confidence_score or 0.0,
        status=p.status.value,
        generated_by=p.generated_by,
        approved_by=p.approved_by,
        applied_at=p.applied_at,
        rejection_reason=p.rejection_reason,
        proposal_data=p.proposal_data,
        rollback_data=p.rollback_data,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


async def _get_proposal_or_404(proposal_id: str, db: AsyncSession) -> AIProposal:
    try:
        uid = UUID(proposal_id)
    except ValueError:
        raise HTTPException(400, "Invalid proposal ID")
    result = await db.execute(select(AIProposal).where(AIProposal.id == uid))
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(404, "Proposal not found")
    return proposal


# ─── Proposal Endpoints ───────────────────────────────────────────────────────

@router.get("/proposals", response_model=list[ProposalResponse])
async def list_proposals(
    status: Optional[str] = Query(None, description="Filter by status: pending, approved, rejected, applied, rolled_back"),
    proposal_type: Optional[str] = Query(None, description="Filter by type: sourcing_rule, custom_attribute, ui_widget, etc."),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    """List AI proposals with optional status/type filters."""
    query = select(AIProposal)
    if status:
        try:
            query = query.where(AIProposal.status == ProposalStatus(status))
        except ValueError:
            raise HTTPException(400, f"Unknown status: {status}")
    if proposal_type:
        try:
            query = query.where(AIProposal.proposal_type == ProposalType(proposal_type))
        except ValueError:
            raise HTTPException(400, f"Unknown proposal_type: {proposal_type}")
    query = query.order_by(AIProposal.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    proposals = result.scalars().all()
    return [_proposal_to_response(p) for p in proposals]


@router.get("/proposals/{proposal_id}", response_model=ProposalResponse)
async def get_proposal(
    proposal_id: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    """Get a single proposal with full rationale and proposal data."""
    proposal = await _get_proposal_or_404(proposal_id, db)
    return _proposal_to_response(proposal)


@router.post("/proposals/{proposal_id}/approve", response_model=ProposalResponse)
async def approve_proposal(
    proposal_id: str,
    user: dict = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Mark a pending proposal as approved. Ready to apply."""
    proposal = await _get_proposal_or_404(proposal_id, db)
    if proposal.status != ProposalStatus.PENDING:
        raise HTTPException(409, f"Proposal is already {proposal.status.value}")
    proposal.status = ProposalStatus.APPROVED
    proposal.approved_by = user.get("email", "unknown")
    await db.commit()
    await db.refresh(proposal)
    logger.info(f"Proposal {proposal_id} approved by {user.get('email')}")
    return _proposal_to_response(proposal)


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalResponse)
async def reject_proposal(
    proposal_id: str,
    payload: RejectRequest,
    user: dict = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Reject a pending or approved proposal with a reason."""
    proposal = await _get_proposal_or_404(proposal_id, db)
    if proposal.status not in (ProposalStatus.PENDING, ProposalStatus.APPROVED):
        raise HTTPException(409, f"Cannot reject a proposal in {proposal.status.value} status")
    proposal.status = ProposalStatus.REJECTED
    proposal.rejection_reason = payload.reason
    await db.commit()
    await db.refresh(proposal)
    logger.info(f"Proposal {proposal_id} rejected by {user.get('email')}: {payload.reason}")
    return _proposal_to_response(proposal)


@router.post("/proposals/{proposal_id}/apply", response_model=ProposalResponse)
async def apply_proposal(
    proposal_id: str,
    user: dict = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """
    Execute an approved proposal. Safe additive-only operations:
    - sourcing_rule: INSERT into sourcing_rules (is_active=false until admin enables)
    - Other types: not yet implemented (Phase 4b)
    """
    proposal = await _get_proposal_or_404(proposal_id, db)
    if proposal.status != ProposalStatus.APPROVED:
        raise HTTPException(409, f"Proposal must be approved before applying (current: {proposal.status.value})")

    # Dispatch to the appropriate apply handler
    if proposal.proposal_type == ProposalType.SOURCING_RULE:
        rollback_data = await _apply_sourcing_rule(proposal, db)
    else:
        raise HTTPException(
            501,
            f"Apply is not yet implemented for proposal type '{proposal.proposal_type.value}'. "
            "This will be available in Phase 4b (Schema Evolution Engine)."
        )

    proposal.status = ProposalStatus.APPLIED
    proposal.applied_at = datetime.utcnow()
    proposal.rollback_data = rollback_data
    await db.commit()
    await db.refresh(proposal)
    logger.info(f"Proposal {proposal_id} applied by {user.get('email')}: {rollback_data}")
    return _proposal_to_response(proposal)


@router.post("/proposals/{proposal_id}/rollback", response_model=ProposalResponse)
async def rollback_proposal(
    proposal_id: str,
    user: dict = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Undo an applied proposal using its stored rollback data."""
    proposal = await _get_proposal_or_404(proposal_id, db)
    if proposal.status != ProposalStatus.APPLIED:
        raise HTTPException(409, f"Only applied proposals can be rolled back (current: {proposal.status.value})")
    if not proposal.rollback_data:
        raise HTTPException(409, "No rollback data available for this proposal")

    if proposal.proposal_type == ProposalType.SOURCING_RULE:
        await _rollback_sourcing_rule(proposal.rollback_data, db)
    else:
        raise HTTPException(501, f"Rollback not implemented for type '{proposal.proposal_type.value}'")

    proposal.status = ProposalStatus.ROLLED_BACK
    await db.commit()
    await db.refresh(proposal)
    logger.info(f"Proposal {proposal_id} rolled back by {user.get('email')}")
    return _proposal_to_response(proposal)


# ─── Apply / Rollback Handlers ────────────────────────────────────────────────

async def _apply_sourcing_rule(proposal: AIProposal, db: AsyncSession) -> dict:
    """
    Insert a new SourcingRule from the proposal data.
    Rule is created with is_active=False — admin must activate it manually.
    Returns rollback_data dict for undo.
    """
    from app.models.postgres.sourcing_rule_models import SourcingRule, SourcingStrategy

    data = proposal.proposal_data or {}
    strategy_str = data.get("strategy", "DISTANCE_OPTIMAL")
    try:
        strategy = SourcingStrategy(strategy_str)
    except ValueError:
        raise HTTPException(400, f"Unknown strategy in proposal: {strategy_str}")

    rule = SourcingRule(
        name=data.get("name", proposal.title),
        description=data.get("description", proposal.description),
        priority=int(data.get("priority", 100)),
        strategy=strategy,
        conditions=data.get("conditions", []),
        max_split_nodes=int(data.get("max_split_nodes", 3)),
        is_active=False,  # Additive-only: admin activates after review
        created_by=f"AI/{proposal.generated_by or 'architect'}",
    )
    db.add(rule)
    await db.flush()
    return {"rule_id": str(rule.id)}


async def _rollback_sourcing_rule(rollback_data: dict, db: AsyncSession) -> None:
    """Delete the sourcing rule that was created by apply."""
    from app.models.postgres.sourcing_rule_models import SourcingRule
    from uuid import UUID

    rule_id = rollback_data.get("rule_id")
    if not rule_id:
        raise HTTPException(500, "rollback_data missing rule_id")
    try:
        uid = UUID(rule_id)
    except ValueError:
        raise HTTPException(500, f"rollback_data contains invalid rule_id: {rule_id!r}")
    result = await db.execute(select(SourcingRule).where(SourcingRule.id == uid))
    rule = result.scalar_one_or_none()
    if rule:
        await db.delete(rule)


# ─── Patterns Endpoint (MongoDB) ──────────────────────────────────────────────

@router.get("/patterns")
async def get_patterns(
    channel: Optional[str] = Query(None),
    limit: int = Query(30, le=100),
    _: dict = Depends(require_superadmin),
    db=Depends(get_mongo_ai_db),
):
    """List discovered sourcing patterns from MongoDB sourcing_patterns collection."""
    query: dict = {}
    if channel:
        query["channel"] = channel

    cursor = db.sourcing_patterns.find(query, {"_id": 0}).sort("sample_count", -1).limit(limit)
    patterns = await cursor.to_list(length=limit)

    # Truncate node_performance to top 5 per cluster for response size
    for p in patterns:
        if "node_performance" in p and len(p["node_performance"]) > 5:
            p["node_performance"] = p["node_performance"][:5]
        if isinstance(p.get("computed_at"), datetime):
            p["computed_at"] = p["computed_at"].isoformat()

    return patterns


# ─── Node Performance Endpoint (MongoDB) ──────────────────────────────────────

@router.get("/node-performance")
async def get_node_performance(
    period_days: int = Query(7, description="7 or 30"),
    limit: int = Query(50, le=200),
    _: dict = Depends(require_superadmin),
    db=Depends(get_mongo_ai_db),
):
    """Rolling node performance metrics from MongoDB node_performance_metrics collection."""
    cursor = (
        db.node_performance_metrics
        .find({"period_days": period_days}, {"_id": 0})
        .sort("avg_outcome_score", -1)
        .limit(limit)
    )
    metrics = await cursor.to_list(length=limit)
    for m in metrics:
        if isinstance(m.get("computed_at"), datetime):
            m["computed_at"] = m["computed_at"].isoformat()
    return metrics


# ─── AI Sourcing Performance (MongoDB) ────────────────────────────────────────

@router.get("/ai-sourcing/performance")
async def get_ai_performance(
    _: dict = Depends(require_superadmin),
    db=Depends(get_mongo_ai_db),
):
    """
    Compare AI_ADAPTIVE vs other strategies using labeled sourcing outcomes.
    Returns per-strategy outcome aggregates and overall summary.
    """
    pipeline = [
        {"$match": {"outcome_score": {"$exists": True}}},
        {
            "$group": {
                "_id": "$strategy_used",
                "count": {"$sum": 1},
                "avg_outcome_score": {"$avg": "$outcome_score"},
                "avg_delivery_hours": {"$avg": "$actual_delivery_hours"},
                "backorder_count": {
                    "$sum": {"$cond": [{"$eq": ["$was_backordered", True]}, 1, 0]}
                },
            }
        },
        {"$sort": {"avg_outcome_score": -1}},
    ]
    strategy_results = await db.sourcing_outcomes.aggregate(pipeline).to_list(length=20)

    total_outcomes = await db.sourcing_outcomes.count_documents({})
    labeled_outcomes = await db.sourcing_outcomes.count_documents({"outcome_score": {"$exists": True}})

    # Find AI_ADAPTIVE and DISTANCE_OPTIMAL to compute improvement %
    by_strategy = {}
    for r in strategy_results:
        strategy = r["_id"] or "UNKNOWN"
        by_strategy[strategy] = r

    ai_score = (by_strategy.get("AI_ADAPTIVE") or {}).get("avg_outcome_score")
    baseline_score = (by_strategy.get("DISTANCE_OPTIMAL") or {}).get("avg_outcome_score")
    improvement_pct = None
    if ai_score is not None and baseline_score and baseline_score > 0:
        improvement_pct = round((ai_score - baseline_score) / baseline_score * 100, 1)

    return {
        "total_outcomes": total_outcomes,
        "labeled_outcomes": labeled_outcomes,
        "unlabeled_outcomes": total_outcomes - labeled_outcomes,
        "ai_improvement_pct": improvement_pct,
        "by_strategy": [
            {
                "strategy": r["_id"] or "UNKNOWN",
                "count": r["count"],
                "avg_outcome_score": round(r["avg_outcome_score"] or 0, 4),
                "avg_delivery_hours": round(r.get("avg_delivery_hours") or 0, 1),
                "backorder_rate_pct": round(r["backorder_count"] / r["count"] * 100, 1) if r["count"] else 0,
            }
            for r in strategy_results
        ],
    }


# ─── Experiment Schemas ───────────────────────────────────────────────────────

class ExperimentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    strategy_a: str = Field(..., description="Control strategy, e.g. DISTANCE_OPTIMAL")
    strategy_b: str = Field(..., description="Treatment strategy, e.g. AI_ADAPTIVE")
    traffic_split_pct: float = Field(10.0, ge=1.0, le=50.0, description="% of orders sent to strategy_b")
    filter_conditions: dict = Field(default_factory=dict, description="Optional: channel, fulfillment_type, region, amount_min, amount_max")


class ExperimentResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    strategy_a: str
    strategy_b: str
    traffic_split_pct: float
    filter_conditions: dict
    status: str
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    winner: Optional[str]
    results: Optional[dict]
    created_at: datetime


def _exp_to_response(exp) -> ExperimentResponse:
    return ExperimentResponse(
        id=str(exp.id),
        name=exp.name,
        description=exp.description,
        strategy_a=exp.strategy_a,
        strategy_b=exp.strategy_b,
        traffic_split_pct=exp.traffic_split_pct,
        filter_conditions=exp.filter_conditions or {},
        status=exp.status.value,
        started_at=exp.started_at,
        ended_at=exp.ended_at,
        winner=exp.winner,
        results=exp.results,
        created_at=exp.created_at,
    )


# ─── Experiment Endpoints ─────────────────────────────────────────────────────

@router.get("/experiments", response_model=list[ExperimentResponse])
async def list_experiments(
    status: Optional[str] = Query(None, description="running, paused, completed"),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    """List A/B experiments."""
    from app.models.postgres.ai_models import AIExperiment, ExperimentStatus
    query = select(AIExperiment).order_by(AIExperiment.started_at.desc())
    if status:
        try:
            query = query.where(AIExperiment.status == ExperimentStatus(status))
        except ValueError:
            raise HTTPException(400, f"Unknown status: {status}")
    result = await db.execute(query)
    return [_exp_to_response(e) for e in result.scalars().all()]


@router.post("/experiments", response_model=ExperimentResponse, status_code=201)
async def create_experiment(
    payload: ExperimentCreate,
    user: dict = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new A/B experiment. Starts immediately in RUNNING status."""
    from app.models.postgres.ai_models import AIExperiment, ExperimentStatus
    from app.models.postgres.sourcing_rule_models import SourcingStrategy
    for field_name, strategy_val in (("strategy_a", payload.strategy_a), ("strategy_b", payload.strategy_b)):
        try:
            SourcingStrategy(strategy_val)
        except ValueError:
            valid = [s.value for s in SourcingStrategy]
            raise HTTPException(400, f"Invalid {field_name} '{strategy_val}'. Valid values: {valid}")
    exp = AIExperiment(
        name=payload.name,
        description=payload.description,
        strategy_a=payload.strategy_a,
        strategy_b=payload.strategy_b,
        traffic_split_pct=payload.traffic_split_pct,
        filter_conditions=payload.filter_conditions,
        status=ExperimentStatus.RUNNING,
    )
    db.add(exp)
    await db.commit()
    await db.refresh(exp)
    logger.info(f"Experiment created by {user.get('email')}: {exp.name} ({exp.strategy_a} vs {exp.strategy_b})")
    return _exp_to_response(exp)


@router.post("/experiments/{experiment_id}/pause", response_model=ExperimentResponse)
async def pause_experiment(
    experiment_id: str,
    user: dict = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Pause a running experiment (stops new orders from being routed to it)."""
    from app.models.postgres.ai_models import AIExperiment, ExperimentStatus
    exp = await _get_experiment_or_404(experiment_id, db)
    if exp.status != ExperimentStatus.RUNNING:
        raise HTTPException(409, f"Experiment is not running (current: {exp.status.value})")
    exp.status = ExperimentStatus.PAUSED
    await db.commit()
    await db.refresh(exp)
    logger.info(f"Experiment {experiment_id} paused by {user.get('email')}")
    return _exp_to_response(exp)


@router.post("/experiments/{experiment_id}/resume", response_model=ExperimentResponse)
async def resume_experiment(
    experiment_id: str,
    user: dict = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Resume a paused experiment."""
    from app.models.postgres.ai_models import AIExperiment, ExperimentStatus
    exp = await _get_experiment_or_404(experiment_id, db)
    if exp.status != ExperimentStatus.PAUSED:
        raise HTTPException(409, f"Experiment is not paused (current: {exp.status.value})")
    exp.status = ExperimentStatus.RUNNING
    await db.commit()
    await db.refresh(exp)
    logger.info(f"Experiment {experiment_id} resumed by {user.get('email')}")
    return _exp_to_response(exp)


@router.get("/experiments/{experiment_id}/results")
async def get_experiment_results(
    experiment_id: str,
    _: dict = Depends(require_superadmin),
    pg_db: AsyncSession = Depends(get_db),
    mongo_db=Depends(get_mongo_ai_db),
):
    """
    Live results for an experiment: per-arm labeled outcome counts and scores from MongoDB.
    """
    exp = await _get_experiment_or_404(experiment_id, pg_db)
    pipeline = [
        {"$match": {"experiment_id": experiment_id, "outcome_score": {"$exists": True}}},
        {
            "$group": {
                "_id": "$strategy_used",
                "count": {"$sum": 1},
                "avg_outcome_score": {"$avg": "$outcome_score"},
                "avg_delivery_hours": {"$avg": "$actual_delivery_hours"},
                "backorder_count": {"$sum": {"$cond": [{"$eq": ["$was_backordered", True]}, 1, 0]}},
            }
        },
    ]
    arm_results = await mongo_db.sourcing_outcomes.aggregate(pipeline).to_list(length=10)

    # Count all outcomes (labeled + unlabeled) for this experiment
    total_a = await mongo_db.sourcing_outcomes.count_documents(
        {"experiment_id": experiment_id, "strategy_used": exp.strategy_a}
    )
    total_b = await mongo_db.sourcing_outcomes.count_documents(
        {"experiment_id": experiment_id, "strategy_used": exp.strategy_b}
    )

    by_strategy = {r["_id"]: r for r in arm_results}

    def arm_summary(strategy: str, total: int) -> dict:
        labeled = by_strategy.get(strategy, {})
        count = labeled.get("count", 0)
        return {
            "strategy": strategy,
            "total_orders": total,
            "labeled_orders": count,
            "avg_outcome_score": round(labeled.get("avg_outcome_score") or 0, 4) if count else None,
            "avg_delivery_hours": round(labeled.get("avg_delivery_hours") or 0, 1) if count else None,
            "backorder_rate_pct": round(labeled.get("backorder_count", 0) / count * 100, 1) if count else None,
        }

    return {
        "experiment_id": experiment_id,
        "experiment_name": exp.name,
        "status": exp.status.value,
        "winner": exp.winner,
        "arms": [
            arm_summary(exp.strategy_a, total_a),
            arm_summary(exp.strategy_b, total_b),
        ],
        "stored_results": exp.results,
    }


async def _get_experiment_or_404(experiment_id: str, db: AsyncSession):
    from app.models.postgres.ai_models import AIExperiment
    try:
        uid = UUID(experiment_id)
    except ValueError:
        raise HTTPException(400, "Invalid experiment ID")
    result = await db.execute(select(AIExperiment).where(AIExperiment.id == uid))
    exp = result.scalar_one_or_none()
    if not exp:
        raise HTTPException(404, "Experiment not found")
    return exp


# ─── Custom Field Definitions ─────────────────────────────────────────────────

class CustomFieldDefinitionCreate(BaseModel):
    entity_type: str = Field(..., description="ORDER, INVENTORY_ITEM, or NODE")
    field_key: str = Field(..., description="Lowercase identifier with underscores, e.g. warranty_code")
    label: str
    data_type: str = Field(..., description="text, number, boolean, or date")
    is_required: bool = False
    default_value: Optional[str] = None


class CustomFieldDefinitionResponse(BaseModel):
    id: str
    entity_type: str
    field_key: str
    label: str
    data_type: str
    is_required: bool
    default_value: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


_VALID_ENTITY_TYPES = {"ORDER", "INVENTORY_ITEM", "NODE"}
_VALID_DATA_TYPES = {"text", "number", "boolean", "date"}

# In-memory store for custom field definitions (persisted to DB via CustomAttributeDefinition model if available,
# otherwise uses a simple in-process list that resets on restart — swap for DB model when schema exists).
_custom_fields: list[dict] = []
_custom_fields_counter = 0


@router.get("/custom-attributes", response_model=list[CustomFieldDefinitionResponse])
async def list_custom_attributes(
    entity_type: Optional[str] = Query(None),
    _: dict = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """List custom field definitions, optionally filtered by entity_type."""
    try:
        from app.models.postgres.ai_models import CustomAttributeDefinition
        query = select(CustomAttributeDefinition).order_by(CustomAttributeDefinition.created_at)
        if entity_type:
            query = query.where(CustomAttributeDefinition.entity_type == entity_type)
        result = await db.execute(query)
        rows = result.scalars().all()
        return [
            CustomFieldDefinitionResponse(
                id=str(r.id),
                entity_type=r.entity_type,
                field_key=r.field_key,
                label=r.label if hasattr(r, "label") else r.field_key,
                data_type=r.data_type if hasattr(r, "data_type") else "text",
                is_required=r.is_required if hasattr(r, "is_required") else False,
                default_value=r.default_value if hasattr(r, "default_value") else None,
                created_at=r.created_at,
            )
            for r in rows
        ]
    except Exception:
        # Fall back to in-memory store if model not yet migrated
        items = _custom_fields if not entity_type else [f for f in _custom_fields if f["entity_type"] == entity_type]
        return [CustomFieldDefinitionResponse(**f) for f in items]


@router.post("/custom-attributes", response_model=CustomFieldDefinitionResponse, status_code=201)
async def create_custom_attribute(
    payload: CustomFieldDefinitionCreate,
    _: dict = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new custom field definition."""
    if payload.entity_type not in _VALID_ENTITY_TYPES:
        raise HTTPException(400, f"entity_type must be one of {sorted(_VALID_ENTITY_TYPES)}")
    if payload.data_type not in _VALID_DATA_TYPES:
        raise HTTPException(400, f"data_type must be one of {sorted(_VALID_DATA_TYPES)}")
    import re
    if not re.match(r"^[a-z][a-z0-9_]*$", payload.field_key):
        raise HTTPException(400, "field_key must start with a lowercase letter and contain only lowercase letters, digits, and underscores")

    try:
        from app.models.postgres.ai_models import CustomAttributeDefinition
        row = CustomAttributeDefinition(
            entity_type=payload.entity_type,
            field_key=payload.field_key,
            label=payload.label,
            data_type=payload.data_type,
            is_required=payload.is_required,
            default_value=payload.default_value,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return CustomFieldDefinitionResponse(
            id=str(row.id),
            entity_type=row.entity_type,
            field_key=row.field_key,
            label=row.label if hasattr(row, "label") else row.field_key,
            data_type=row.data_type if hasattr(row, "data_type") else "text",
            is_required=row.is_required if hasattr(row, "is_required") else False,
            default_value=row.default_value if hasattr(row, "default_value") else None,
            created_at=row.created_at,
        )
    except Exception:
        # Fall back to in-memory store
        global _custom_fields_counter
        _custom_fields_counter += 1
        now = datetime.utcnow()
        record = {
            "id": str(_custom_fields_counter),
            "entity_type": payload.entity_type,
            "field_key": payload.field_key,
            "label": payload.label,
            "data_type": payload.data_type,
            "is_required": payload.is_required,
            "default_value": payload.default_value,
            "created_at": now,
        }
        _custom_fields.append(record)
        return CustomFieldDefinitionResponse(**record)


@router.delete("/custom-attributes/{field_id}", status_code=204)
async def delete_custom_attribute(
    field_id: str,
    _: dict = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a custom field definition by ID."""
    try:
        from app.models.postgres.ai_models import CustomAttributeDefinition
        try:
            uid = UUID(field_id)
        except ValueError:
            raise HTTPException(400, "Invalid field ID")
        result = await db.execute(select(CustomAttributeDefinition).where(CustomAttributeDefinition.id == uid))
        row = result.scalar_one_or_none()
        if not row:
            raise HTTPException(404, "Custom field not found")
        await db.delete(row)
        await db.commit()
        return
    except HTTPException:
        raise
    except Exception:
        # Fall back to in-memory store
        global _custom_fields
        before = len(_custom_fields)
        _custom_fields = [f for f in _custom_fields if f["id"] != field_id]
        if len(_custom_fields) == before:
            raise HTTPException(404, "Custom field not found")
