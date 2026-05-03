"""Lifecycle router — CRUD for order pipeline configurations."""
import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.postgres import get_db
from app.models.postgres.lifecycle_models import Lifecycle, LifecycleStep
from app.schemas.lifecycles import (
    LifecycleCreate, LifecycleUpdate, LifecycleResponse, LifecycleResolveResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/lifecycles", tags=["Lifecycles"])


def _require_superadmin(request):
    user = getattr(request.state, "user", {}) or {}
    if not user.get("is_superadmin"):
        raise HTTPException(status_code=403, detail="Superadmin required")


async def _get_with_steps(lifecycle_id: UUID, db: AsyncSession) -> Lifecycle:
    result = await db.execute(
        select(Lifecycle)
        .options(selectinload(Lifecycle.steps))
        .where(Lifecycle.id == lifecycle_id)
    )
    lc = result.scalar_one_or_none()
    if not lc:
        raise HTTPException(status_code=404, detail="Lifecycle not found")
    return lc


def _apply_steps(lc: Lifecycle, steps_data) -> None:
    """Replace all steps on a lifecycle with the provided data."""
    lc.steps.clear()
    for i, s in enumerate(steps_data):
        lc.steps.append(LifecycleStep(
            lifecycle_id=lc.id,
            status=s.status,
            label=s.label,
            description=s.description or "",
            step_order=s.step_order if s.step_order is not None else i,
            allowed_next_statuses=s.allowed_next_statuses or [],
            action_type=s.action_type,
            sla_hours=s.sla_hours,
        ))


# ── List ────────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[LifecycleResponse])
async def list_lifecycles(
    fulfillment_type: Optional[str] = Query(None),
    active_only: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    q = select(Lifecycle).options(selectinload(Lifecycle.steps))
    if active_only:
        q = q.where(Lifecycle.is_active == True)
    if fulfillment_type:
        # JSON contains check — works with PostgreSQL json[] column
        q = q.where(Lifecycle.fulfillment_types.contains([fulfillment_type]))
    result = await db.execute(q)
    return result.scalars().all()


# ── Resolve ──────────────────────────────────────────────────────────────────

@router.get("/resolve", response_model=LifecycleResolveResponse)
async def resolve_lifecycle(
    fulfillment_type: str = Query(...),
    channel: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Return the best matching active lifecycle for the given context."""
    from app.services.lifecycle_engine import resolve_lifecycle as _resolve
    lc, matched_on = await _resolve(db, fulfillment_type, channel)
    return LifecycleResolveResponse(lifecycle=lc, matched_on=matched_on)


# ── Create ───────────────────────────────────────────────────────────────────

@router.post("/", response_model=LifecycleResponse, status_code=201)
async def create_lifecycle(
    payload: LifecycleCreate,
    db: AsyncSession = Depends(get_db),
):
    lc = Lifecycle(
        name=payload.name,
        description=payload.description,
        fulfillment_types=payload.fulfillment_types or [],
        channels=payload.channels or [],
        is_active=payload.is_active,
        is_default=payload.is_default,
        created_by=payload.created_by,
    )
    db.add(lc)
    await db.flush()
    _apply_steps(lc, payload.steps)
    await db.flush()

    result = await db.execute(
        select(Lifecycle).options(selectinload(Lifecycle.steps)).where(Lifecycle.id == lc.id)
    )
    return result.scalar_one()


# ── Get ──────────────────────────────────────────────────────────────────────

@router.get("/{lifecycle_id}", response_model=LifecycleResponse)
async def get_lifecycle(lifecycle_id: UUID, db: AsyncSession = Depends(get_db)):
    return await _get_with_steps(lifecycle_id, db)


# ── Update ───────────────────────────────────────────────────────────────────

@router.patch("/{lifecycle_id}", response_model=LifecycleResponse)
async def update_lifecycle(
    lifecycle_id: UUID,
    payload: LifecycleUpdate,
    db: AsyncSession = Depends(get_db),
):
    lc = await _get_with_steps(lifecycle_id, db)

    if payload.name is not None:
        lc.name = payload.name
    if payload.description is not None:
        lc.description = payload.description
    if payload.fulfillment_types is not None:
        lc.fulfillment_types = payload.fulfillment_types
    if payload.channels is not None:
        lc.channels = payload.channels
    if payload.is_active is not None:
        lc.is_active = payload.is_active
    if payload.is_default is not None:
        lc.is_default = payload.is_default
    if payload.steps is not None:
        _apply_steps(lc, payload.steps)

    await db.flush()
    result = await db.execute(
        select(Lifecycle).options(selectinload(Lifecycle.steps)).where(Lifecycle.id == lc.id)
    )
    return result.scalar_one()


# ── Delete ───────────────────────────────────────────────────────────────────

@router.delete("/{lifecycle_id}", status_code=204)
async def delete_lifecycle(lifecycle_id: UUID, db: AsyncSession = Depends(get_db)):
    lc = await _get_with_steps(lifecycle_id, db)
    await db.delete(lc)
