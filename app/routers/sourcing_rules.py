"""Sourcing Rules router — CRUD for configurable sourcing strategies."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from uuid import UUID

from app.database.postgres import get_db
from app.dependencies.auth import get_current_user, require_superadmin
from app.models.postgres.sourcing_rule_models import SourcingRule, SourcingStrategy
from app.models.postgres.node_models import NodeType
from app.schemas.sourcing_rules import (
    SourcingRuleCreate, SourcingRuleUpdate, SourcingRuleResponse,
    SourcingRuleListResponse, SourcingRequest, SourcingResult,
)

router = APIRouter(
    prefix="/sourcing-rules",
    tags=["Sourcing Rules"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/metadata", response_model=dict)
async def get_sourcing_metadata():
    """Return all available strategies, node types, condition operators, and node capabilities."""
    return {
        "strategies": [s.value for s in SourcingStrategy],
        "node_types": [t.value for t in NodeType],
        "operators": [
            "EQUALS", "NOT_EQUALS",
            "GREATER_THAN", "LESS_THAN",
            "GREATER_THAN_OR_EQUAL", "LESS_THAN_OR_EQUAL",
            "IN", "NOT_IN", "CONTAINS", "STARTS_WITH",
        ],
        "capabilities": ["can_ship", "can_pickup", "can_curbside", "can_same_day"],
        "condition_fields": [
            {"field": "channel", "label": "Channel", "group": "Order", "values": ["WEB", "MOBILE", "POS", "API", "MARKETPLACE", "B2B", "EDI", "WHOLESALE"]},
            {"field": "fulfillment_type", "label": "Fulfillment Type", "group": "Order", "values": ["SHIP_TO_HOME", "STORE_PICKUP", "SHIP_FROM_STORE", "CURBSIDE_PICKUP", "SAME_DAY_DELIVERY"]},
            {"field": "total_amount", "label": "Order Total ($)", "group": "Order", "values": []},
            {"field": "currency", "label": "Currency", "group": "Order", "values": ["USD", "CAD", "GBP", "EUR"]},
            {"field": "shipping_country", "label": "Shipping Country", "group": "Order", "values": ["US", "CA", "GB", "AU"]},
            {"field": "shipping_state", "label": "Shipping State/Province", "group": "Order", "values": []},
            {"field": "customer_email", "label": "Customer Email", "group": "Order", "values": []},
            {"field": "order_type", "label": "Order Type", "group": "B2B", "values": ["RETAIL", "B2B"]},
            {"field": "payment_terms", "label": "Payment Terms", "group": "B2B", "values": ["PREPAID", "NET15", "NET30", "NET60", "NET90", "COD"]},
            {"field": "approval_status", "label": "Approval Status", "group": "B2B", "values": ["NOT_REQUIRED", "PENDING", "APPROVED", "REJECTED"]},
            {"field": "po_number", "label": "PO Number", "group": "B2B", "values": []},
            {"field": "brand_id",   "label": "Brand (by ID)",   "group": "Brand", "values": []},
            {"field": "brand_slug", "label": "Brand (by slug)",  "group": "Brand", "values": []},
            {"field": "has_sku", "label": "Has SKU", "group": "Line Items", "type": "boolean", "values": []},
            {"field": "max_item_weight_lbs", "label": "Max Item Weight (lbs)", "group": "Line Items", "type": "number", "values": []},
        ],
    }


@router.post("/", response_model=SourcingRuleResponse, status_code=201,
             dependencies=[Depends(require_superadmin)])
async def create_sourcing_rule(payload: SourcingRuleCreate, db: AsyncSession = Depends(get_db)):
    conditions = [c.model_dump() for c in payload.conditions]
    rule = SourcingRule(
        name=payload.name,
        description=payload.description,
        priority=payload.priority,
        is_active=payload.is_active,
        strategy=payload.strategy,
        conditions=conditions,
        allowed_node_types=payload.allowed_node_types,
        excluded_node_ids=payload.excluded_node_ids,
        required_capabilities=payload.required_capabilities,
        max_split_nodes=payload.max_split_nodes,
        max_distance_km=payload.max_distance_km,
        cost_weight=payload.cost_weight,
        distance_weight=payload.distance_weight,
        created_by=payload.created_by,
    )
    db.add(rule)
    await db.flush()
    await db.refresh(rule)
    return rule


@router.get("/", response_model=SourcingRuleListResponse)
async def list_sourcing_rules(
    is_active: Optional[bool] = None,
    brand_id: Optional[str] = Query(default=None, description="Filter rules by brand UUID"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(SourcingRule).order_by(SourcingRule.priority.asc())
    if is_active is not None:
        query = query.where(SourcingRule.is_active == is_active)
    if brand_id is not None:
        query = query.where(SourcingRule.brand_id == brand_id)

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    rules = result.scalars().all()
    return SourcingRuleListResponse(items=rules, total=total)


@router.get("/{rule_id}", response_model=SourcingRuleResponse)
async def get_sourcing_rule(rule_id: UUID, db: AsyncSession = Depends(get_db)):
    rule = await db.get(SourcingRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Sourcing rule not found")
    return rule


@router.patch("/{rule_id}", response_model=SourcingRuleResponse,
              dependencies=[Depends(require_superadmin)])
async def update_sourcing_rule(
    rule_id: UUID, payload: SourcingRuleUpdate, db: AsyncSession = Depends(get_db)
):
    rule = await db.get(SourcingRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Sourcing rule not found")

    update_data = payload.model_dump(exclude_unset=True)
    if "conditions" in update_data and update_data["conditions"]:
        update_data["conditions"] = [
            c.model_dump() if hasattr(c, "model_dump") else c
            for c in update_data["conditions"]
        ]

    for field, value in update_data.items():
        setattr(rule, field, value)

    await db.flush()
    await db.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=204,
               dependencies=[Depends(require_superadmin)])
async def delete_sourcing_rule(rule_id: UUID, db: AsyncSession = Depends(get_db)):
    rule = await db.get(SourcingRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Sourcing rule not found")
    await db.delete(rule)
    await db.flush()


@router.post("/{rule_id}/toggle", response_model=SourcingRuleResponse,
             dependencies=[Depends(require_superadmin)])
async def toggle_sourcing_rule(rule_id: UUID, db: AsyncSession = Depends(get_db)):
    rule = await db.get(SourcingRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Sourcing rule not found")
    rule.is_active = not rule.is_active
    await db.flush()
    await db.refresh(rule)
    return rule


@router.post("/evaluate", response_model=SourcingResult,
             dependencies=[Depends(require_superadmin)])
async def evaluate_sourcing(payload: SourcingRequest, db: AsyncSession = Depends(get_db)):
    """Manually trigger sourcing evaluation for an order."""
    from app.services.sourcing_engine import SourcingEngine
    from app.models.postgres.order_models import Order
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(Order)
        .options(selectinload(Order.line_items))
        .where(Order.id == payload.order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    engine = SourcingEngine(db)
    return await engine.source_order(order, force_strategy=payload.force_strategy)
