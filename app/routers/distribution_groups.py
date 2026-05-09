"""Distribution Groups router — CRUD for DG management."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from typing import Optional
from uuid import UUID

from app.database.postgres import get_db
from app.dependencies.auth import get_current_user, require_superadmin
from app.models.postgres.sourcing_rule_models import DistributionGroup, DistributionGroupMember
from app.models.postgres.node_models import FulfillmentNode
from app.schemas.sourcing_rules import (
    DistributionGroupCreate, DistributionGroupUpdate,
    DistributionGroupResponse, DistributionGroupListResponse,
    DGMemberCreate, DGMemberResponse,
)

router = APIRouter(
    prefix="/distribution-groups",
    tags=["Distribution Groups"],
    dependencies=[Depends(get_current_user)],
)


async def _get_dg(dg_id: UUID, db: AsyncSession) -> DistributionGroup:
    result = await db.execute(
        select(DistributionGroup)
        .options(selectinload(DistributionGroup.members).selectinload(DistributionGroupMember.node))
        .where(DistributionGroup.id == dg_id)
    )
    dg = result.scalar_one_or_none()
    if not dg:
        raise HTTPException(status_code=404, detail="Distribution group not found")
    return dg


def _member_response(m: DistributionGroupMember) -> DGMemberResponse:
    node = m.node
    return DGMemberResponse(
        id=m.id,
        group_id=m.group_id,
        node_id=m.node_id,
        priority=m.priority,
        node_name=node.name if node else None,
        node_code=node.code if node else None,
        node_type=node.node_type.value if node and node.node_type else None,
    )


def _dg_response(dg: DistributionGroup) -> DistributionGroupResponse:
    return DistributionGroupResponse(
        id=dg.id,
        name=dg.name,
        description=dg.description,
        is_active=dg.is_active,
        brand_id=dg.brand_id,
        created_at=dg.created_at,
        updated_at=dg.updated_at,
        members=[_member_response(m) for m in sorted(dg.members, key=lambda x: x.priority)],
    )


# ── List ────────────────────────────────────────────────────────────────────

@router.get("/", response_model=DistributionGroupListResponse)
async def list_distribution_groups(
    is_active: Optional[bool] = None,
    brand_id: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(DistributionGroup)
        .options(selectinload(DistributionGroup.members).selectinload(DistributionGroupMember.node))
        .order_by(DistributionGroup.name.asc())
    )
    if is_active is not None:
        q = q.where(DistributionGroup.is_active == is_active)
    if brand_id:
        q = q.where(DistributionGroup.brand_id == brand_id)

    count_q = select(func.count()).select_from(
        select(DistributionGroup.id)
        .where(*(
            ([DistributionGroup.is_active == is_active] if is_active is not None else []) +
            ([DistributionGroup.brand_id == brand_id] if brand_id else [])
        )).subquery()
    )
    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    dgs = result.scalars().all()
    return DistributionGroupListResponse(
        items=[_dg_response(dg) for dg in dgs],
        total=total,
    )


# ── Create ───────────────────────────────────────────────────────────────────

@router.post("/", response_model=DistributionGroupResponse, status_code=201,
             dependencies=[Depends(require_superadmin)])
async def create_distribution_group(
    payload: DistributionGroupCreate,
    db: AsyncSession = Depends(get_db),
):
    dg = DistributionGroup(
        name=payload.name,
        description=payload.description,
        is_active=payload.is_active,
        brand_id=payload.brand_id or None,
    )
    db.add(dg)
    await db.flush()

    for m in payload.members:
        node = await db.get(FulfillmentNode, m.node_id)
        if not node:
            raise HTTPException(status_code=422, detail=f"Node {m.node_id} not found")
        db.add(DistributionGroupMember(
            group_id=dg.id,
            node_id=m.node_id,
            priority=m.priority,
        ))
    await db.flush()

    return _dg_response(await _get_dg(dg.id, db))


# ── Get ──────────────────────────────────────────────────────────────────────

@router.get("/{dg_id}", response_model=DistributionGroupResponse)
async def get_distribution_group(dg_id: UUID, db: AsyncSession = Depends(get_db)):
    return _dg_response(await _get_dg(dg_id, db))


# ── Update ───────────────────────────────────────────────────────────────────

@router.patch("/{dg_id}", response_model=DistributionGroupResponse,
              dependencies=[Depends(require_superadmin)])
async def update_distribution_group(
    dg_id: UUID,
    payload: DistributionGroupUpdate,
    db: AsyncSession = Depends(get_db),
):
    dg = await _get_dg(dg_id, db)
    if payload.name is not None:
        dg.name = payload.name
    if payload.description is not None:
        dg.description = payload.description
    if payload.is_active is not None:
        dg.is_active = payload.is_active
    if payload.brand_id is not None:
        dg.brand_id = payload.brand_id or None
    await db.flush()
    return _dg_response(await _get_dg(dg_id, db))


# ── Delete ───────────────────────────────────────────────────────────────────

@router.delete("/{dg_id}", status_code=204,
               dependencies=[Depends(require_superadmin)])
async def delete_distribution_group(dg_id: UUID, db: AsyncSession = Depends(get_db)):
    dg = await _get_dg(dg_id, db)
    await db.delete(dg)
    await db.flush()


# ── Members ───────────────────────────────────────────────────────────────────

@router.post("/{dg_id}/members", response_model=DistributionGroupResponse,
             dependencies=[Depends(require_superadmin)])
async def add_member(
    dg_id: UUID,
    payload: DGMemberCreate,
    db: AsyncSession = Depends(get_db),
):
    dg = await _get_dg(dg_id, db)
    node = await db.get(FulfillmentNode, payload.node_id)
    if not node:
        raise HTTPException(status_code=422, detail="Node not found")
    # Check for existing membership
    existing = await db.execute(
        select(DistributionGroupMember).where(
            DistributionGroupMember.group_id == dg_id,
            DistributionGroupMember.node_id == payload.node_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Node already in this distribution group")
    db.add(DistributionGroupMember(
        group_id=dg_id,
        node_id=payload.node_id,
        priority=payload.priority,
    ))
    await db.flush()
    return _dg_response(await _get_dg(dg_id, db))


@router.patch("/{dg_id}/members/{node_id}", response_model=DistributionGroupResponse,
              dependencies=[Depends(require_superadmin)])
async def update_member_priority(
    dg_id: UUID,
    node_id: UUID,
    payload: DGMemberCreate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DistributionGroupMember).where(
            DistributionGroupMember.group_id == dg_id,
            DistributionGroupMember.node_id == node_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    member.priority = payload.priority
    await db.flush()
    return _dg_response(await _get_dg(dg_id, db))


@router.delete("/{dg_id}/members/{node_id}", response_model=DistributionGroupResponse,
               dependencies=[Depends(require_superadmin)])
async def remove_member(
    dg_id: UUID,
    node_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DistributionGroupMember).where(
            DistributionGroupMember.group_id == dg_id,
            DistributionGroupMember.node_id == node_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    await db.delete(member)
    await db.flush()
    return _dg_response(await _get_dg(dg_id, db))
