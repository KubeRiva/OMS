"""Brands router — CRUD for logical brand entities within an environment."""
import uuid as _uuid
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.postgres import get_db
from app.dependencies.auth import require_superadmin
from app.models.postgres.brand_models import Brand, BrandConfig, BrandNode
from app.models.postgres.connector_models import Connector
from app.models.postgres.node_models import FulfillmentNode
from app.models.postgres.order_models import Order
from app.models.postgres.b2b_models import CustomerAccount
from app.models.postgres.sourcing_rule_models import SourcingRule
from app.schemas.brands import (
    BrandCloneRequest,
    BrandConfigCreate,
    BrandConfigResponse,
    BrandCreate,
    BrandNodeCreate,
    BrandNodeResponse,
    BrandResponse,
    BrandUpdate,
)

router = APIRouter(prefix="/brands", tags=["Brands"])


async def _count_brand_children(db: AsyncSession, brand_id: UUID) -> tuple[int, int, int]:
    """Return (order_count, rule_count, account_count) for a brand."""
    order_count = (
        await db.execute(select(func.count()).where(Order.brand_id == brand_id))
    ).scalar_one()
    rule_count = (
        await db.execute(select(func.count()).where(SourcingRule.brand_id == brand_id))
    ).scalar_one()
    account_count = (
        await db.execute(select(func.count()).where(CustomerAccount.brand_id == brand_id))
    ).scalar_one()
    return order_count, rule_count, account_count


def _to_response(brand: Brand, order_count: int = 0, rule_count: int = 0, account_count: int = 0) -> BrandResponse:
    return BrandResponse(
        id=brand.id,
        slug=brand.slug,
        name=brand.name,
        tenant_mode=brand.tenant_mode,
        description=brand.description,
        is_active=brand.is_active,
        inventory_mode=brand.inventory_mode,
        created_at=brand.created_at,
        updated_at=brand.updated_at,
        order_count=order_count,
        rule_count=rule_count,
        account_count=account_count,
    )


# ---------------------------------------------------------------------------
# Brand CRUD
# ---------------------------------------------------------------------------

@router.post("/", response_model=BrandResponse, status_code=201,
             dependencies=[Depends(require_superadmin)])
async def create_brand(
    payload: BrandCreate,
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        select(Brand).where(Brand.slug == payload.slug)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"Brand with slug '{payload.slug}' already exists")

    brand = Brand(
        slug=payload.slug,
        name=payload.name,
        tenant_mode=payload.tenant_mode,
        description=payload.description,
        inventory_mode=payload.inventory_mode.value,
    )
    db.add(brand)
    await db.flush()
    await db.refresh(brand)
    return _to_response(brand)


@router.get("/", response_model=list[BrandResponse],
            dependencies=[Depends(require_superadmin)])
async def list_brands(
    is_active: Optional[bool] = Query(default=None),
    tenant_mode: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Brand).order_by(Brand.name)
    if is_active is not None:
        stmt = stmt.where(Brand.is_active == is_active)
    if tenant_mode is not None:
        stmt = stmt.where(Brand.tenant_mode == tenant_mode)
    stmt = stmt.offset(offset).limit(limit)

    brands = (await db.execute(stmt)).scalars().all()

    result = []
    for brand in brands:
        oc, rc, ac = await _count_brand_children(db, brand.id)
        result.append(_to_response(brand, oc, rc, ac))
    return result


@router.get("/{brand_id}", response_model=BrandResponse,
            dependencies=[Depends(require_superadmin)])
async def get_brand(
    brand_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    brand = await db.get(Brand, brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")
    oc, rc, ac = await _count_brand_children(db, brand_id)
    return _to_response(brand, oc, rc, ac)


@router.patch("/{brand_id}", response_model=BrandResponse,
              dependencies=[Depends(require_superadmin)])
async def update_brand(
    brand_id: UUID,
    payload: BrandUpdate,
    db: AsyncSession = Depends(get_db),
):
    brand = await db.get(Brand, brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")

    update_data = payload.model_dump(exclude_unset=True)
    # slug is intentionally excluded from BrandUpdate — cannot be changed after creation
    for field, value in update_data.items():
        # Store enum values as their string representation
        if hasattr(value, "value"):
            value = value.value
        setattr(brand, field, value)

    await db.flush()
    await db.refresh(brand)
    oc, rc, ac = await _count_brand_children(db, brand_id)
    return _to_response(brand, oc, rc, ac)


@router.delete("/{brand_id}", status_code=204,
               dependencies=[Depends(require_superadmin)])
async def delete_brand(
    brand_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    brand = await db.get(Brand, brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")

    oc, rc, ac = await _count_brand_children(db, brand_id)
    if oc > 0 or rc > 0 or ac > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot delete brand '{brand.slug}': "
                f"{oc} order(s), {rc} sourcing rule(s), {ac} customer account(s) are linked to it."
            ),
        )

    await db.delete(brand)
    await db.flush()


@router.post("/{brand_id}/toggle", response_model=BrandResponse,
             dependencies=[Depends(require_superadmin)])
async def toggle_brand(
    brand_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    brand = await db.get(Brand, brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")

    brand.is_active = not brand.is_active
    await db.flush()
    await db.refresh(brand)
    oc, rc, ac = await _count_brand_children(db, brand_id)
    return _to_response(brand, oc, rc, ac)


# ---------------------------------------------------------------------------
# BrandConfig endpoints
# ---------------------------------------------------------------------------

@router.get("/{brand_id}/config", response_model=BrandConfigResponse,
            dependencies=[Depends(require_superadmin)])
async def get_brand_config(
    brand_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Return the brand's operational config. Returns defaults if not yet set."""
    brand = await db.get(Brand, brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")

    result = await db.execute(
        select(BrandConfig).where(BrandConfig.brand_id == brand_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        # Return a default config (not persisted) so callers can see defaults
        from datetime import datetime as _dt
        now = _dt.utcnow()
        return BrandConfigResponse(
            id=brand_id,  # placeholder — not persisted
            brand_id=brand_id,
            default_currency="USD",
            default_locale="en-US",
            sla_ship_hours=48,
            sla_deliver_days=5,
            return_window_days=30,
            logo_url=None,
            support_email=None,
            support_phone=None,
            default_fulfillment_type=None,
            auto_approve_orders=False,
            ai_sourcing_enabled=True,
            created_at=now,
            updated_at=now,
        )
    return config


@router.put("/{brand_id}/config", response_model=BrandConfigResponse,
            dependencies=[Depends(require_superadmin)])
async def upsert_brand_config(
    brand_id: UUID,
    payload: BrandConfigCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create or update the brand's operational config (upsert)."""
    brand = await db.get(Brand, brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")

    result = await db.execute(
        select(BrandConfig).where(BrandConfig.brand_id == brand_id)
    )
    config = result.scalar_one_or_none()

    if config is None:
        config = BrandConfig(brand_id=brand_id, **payload.model_dump())
        db.add(config)
    else:
        for field, value in payload.model_dump().items():
            setattr(config, field, value)

    await db.flush()
    await db.refresh(config)
    return config


# ---------------------------------------------------------------------------
# BrandNode endpoints
# ---------------------------------------------------------------------------

@router.get("/{brand_id}/nodes", response_model=list[BrandNodeResponse],
            dependencies=[Depends(require_superadmin)])
async def list_brand_nodes(
    brand_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """List all fulfillment nodes assigned to this brand, ordered by priority."""
    brand = await db.get(Brand, brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")

    result = await db.execute(
        select(BrandNode, FulfillmentNode.name, FulfillmentNode.code)
        .join(FulfillmentNode, BrandNode.node_id == FulfillmentNode.id)
        .where(BrandNode.brand_id == brand_id)
        .order_by(BrandNode.priority.asc())
    )
    rows = result.all()

    return [
        BrandNodeResponse(
            id=bn.id,
            brand_id=bn.brand_id,
            node_id=bn.node_id,
            priority=bn.priority,
            is_active=bn.is_active,
            max_daily_orders=bn.max_daily_orders,
            node_name=node_name,
            node_code=node_code,
            created_at=bn.created_at,
        )
        for bn, node_name, node_code in rows
    ]


@router.post("/{brand_id}/nodes", response_model=BrandNodeResponse, status_code=201,
             dependencies=[Depends(require_superadmin)])
async def assign_node_to_brand(
    brand_id: UUID,
    payload: BrandNodeCreate,
    db: AsyncSession = Depends(get_db),
):
    """Assign a fulfillment node to this brand with an optional priority and daily cap."""
    brand = await db.get(Brand, brand_id)
    if not brand:
        raise HTTPException(status_code=404, detail="Brand not found")

    node = await db.get(FulfillmentNode, payload.node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Fulfillment node not found")

    # Check for duplicate
    existing = (await db.execute(
        select(BrandNode).where(
            BrandNode.brand_id == brand_id,
            BrandNode.node_id == payload.node_id,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Node '{node.code}' is already assigned to this brand",
        )

    brand_node = BrandNode(
        brand_id=brand_id,
        node_id=payload.node_id,
        priority=payload.priority,
        is_active=payload.is_active,
        max_daily_orders=payload.max_daily_orders,
    )
    db.add(brand_node)
    await db.flush()
    await db.refresh(brand_node)

    return BrandNodeResponse(
        id=brand_node.id,
        brand_id=brand_node.brand_id,
        node_id=brand_node.node_id,
        priority=brand_node.priority,
        is_active=brand_node.is_active,
        max_daily_orders=brand_node.max_daily_orders,
        node_name=node.name,
        node_code=node.code,
        created_at=brand_node.created_at,
    )


@router.delete("/{brand_id}/nodes/{node_id}", status_code=204,
               dependencies=[Depends(require_superadmin)])
async def remove_node_from_brand(
    brand_id: UUID,
    node_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Remove a node assignment from this brand."""
    brand_node = (await db.execute(
        select(BrandNode).where(
            BrandNode.brand_id == brand_id,
            BrandNode.node_id == node_id,
        )
    )).scalar_one_or_none()
    if not brand_node:
        raise HTTPException(status_code=404, detail="Brand-node assignment not found")

    await db.delete(brand_node)
    await db.flush()


# ---------------------------------------------------------------------------
# Brand clone
# ---------------------------------------------------------------------------

@router.post("/{brand_id}/clone", response_model=BrandResponse, status_code=201,
             dependencies=[Depends(require_superadmin)])
async def clone_brand(
    brand_id: UUID,
    payload: BrandCloneRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Clone a brand: creates a new brand and optionally copies its BrandConfig,
    BrandNode assignments, and SourcingRules (as inactive copies with '(Clone)'
    suffix on the rule name).
    """
    source = await db.get(Brand, brand_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source brand not found")

    # Check slug uniqueness for clone target
    slug_conflict = (await db.execute(
        select(Brand).where(Brand.slug == payload.slug)
    )).scalar_one_or_none()
    if slug_conflict:
        raise HTTPException(
            status_code=409,
            detail=f"Brand with slug '{payload.slug}' already exists",
        )

    # Create new brand
    cloned = Brand(
        slug=payload.slug,
        name=payload.name,
        tenant_mode=payload.tenant_mode.value,
        description=source.description,
        inventory_mode=source.inventory_mode,
        is_active=True,
    )
    db.add(cloned)
    await db.flush()  # need cloned.id

    # Clone BrandConfig
    if payload.clone_config:
        src_cfg_result = await db.execute(
            select(BrandConfig).where(BrandConfig.brand_id == brand_id)
        )
        src_cfg = src_cfg_result.scalar_one_or_none()
        if src_cfg:
            new_cfg = BrandConfig(
                brand_id=cloned.id,
                default_currency=src_cfg.default_currency,
                default_locale=src_cfg.default_locale,
                sla_ship_hours=src_cfg.sla_ship_hours,
                sla_deliver_days=src_cfg.sla_deliver_days,
                return_window_days=src_cfg.return_window_days,
                logo_url=src_cfg.logo_url,
                support_email=src_cfg.support_email,
                support_phone=src_cfg.support_phone,
                default_fulfillment_type=src_cfg.default_fulfillment_type,
                auto_approve_orders=src_cfg.auto_approve_orders,
                ai_sourcing_enabled=src_cfg.ai_sourcing_enabled,
            )
            db.add(new_cfg)

    # Clone BrandNode assignments
    if payload.clone_nodes:
        src_nodes_result = await db.execute(
            select(BrandNode).where(BrandNode.brand_id == brand_id)
        )
        src_nodes = src_nodes_result.scalars().all()
        for bn in src_nodes:
            db.add(BrandNode(
                brand_id=cloned.id,
                node_id=bn.node_id,
                priority=bn.priority,
                is_active=bn.is_active,
                max_daily_orders=bn.max_daily_orders,
            ))

    # Clone SourcingRules (inactive copies with "(Clone)" suffix)
    if payload.clone_sourcing_rules:
        src_rules_result = await db.execute(
            select(SourcingRule).where(SourcingRule.brand_id == brand_id)
        )
        src_rules = src_rules_result.scalars().all()
        import copy as _copy
        for rule in src_rules:
            db.add(SourcingRule(
                brand_id=cloned.id,
                name=f"{rule.name} (Clone)",
                description=rule.description,
                priority=rule.priority,
                strategy=rule.strategy,
                conditions=_copy.deepcopy(rule.conditions) if rule.conditions else [],
                allowed_node_types=list(rule.allowed_node_types) if rule.allowed_node_types else [],
                excluded_node_ids=list(rule.excluded_node_ids) if rule.excluded_node_ids else [],
                required_capabilities=list(rule.required_capabilities) if rule.required_capabilities else [],
                max_split_nodes=rule.max_split_nodes,
                max_distance_km=rule.max_distance_km,
                cost_weight=rule.cost_weight,
                distance_weight=rule.distance_weight,
                is_active=False,  # cloned rules start inactive — human must enable
            ))

    await db.flush()
    await db.refresh(cloned)
    return _to_response(cloned)
