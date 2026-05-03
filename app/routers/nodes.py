"""Fulfillment Nodes router — DCs and Stores."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from typing import Optional
from uuid import UUID

from app.database.postgres import get_db
from app.models.postgres.node_models import FulfillmentNode, NodeStatus, NodeType
from app.schemas.nodes import NodeCreate, NodeUpdate, NodeResponse, NodeListResponse

router = APIRouter(prefix="/nodes", tags=["Fulfillment Nodes"])


@router.post("/", response_model=NodeResponse, status_code=201)
async def create_node(payload: NodeCreate, db: AsyncSession = Depends(get_db)):
    # Check code uniqueness
    result = await db.execute(select(FulfillmentNode).where(FulfillmentNode.code == payload.code))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Node with code '{payload.code}' already exists")

    node = FulfillmentNode(**payload.model_dump())
    db.add(node)
    await db.flush()
    await db.refresh(node)
    return node


@router.get("/", response_model=NodeListResponse)
async def list_nodes(
    node_type: Optional[NodeType] = None,
    status: Optional[NodeStatus] = None,
    can_ship: Optional[bool] = None,
    can_pickup: Optional[bool] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    query = select(FulfillmentNode)
    if node_type:
        query = query.where(FulfillmentNode.node_type == node_type)
    if status:
        query = query.where(FulfillmentNode.status == status)
    if can_ship is not None:
        query = query.where(FulfillmentNode.can_ship == can_ship)
    if can_pickup is not None:
        query = query.where(FulfillmentNode.can_pickup == can_pickup)

    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    nodes = result.scalars().all()
    return NodeListResponse(items=nodes, total=total)


@router.get("/{node_id}", response_model=NodeResponse)
async def get_node(node_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FulfillmentNode).where(FulfillmentNode.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@router.patch("/{node_id}", response_model=NodeResponse)
async def update_node(node_id: UUID, payload: NodeUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FulfillmentNode).where(FulfillmentNode.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(node, field, value)

    await db.flush()
    await db.refresh(node)
    return node


@router.delete("/{node_id}", status_code=204)
async def deactivate_node(node_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FulfillmentNode).where(FulfillmentNode.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    node.status = NodeStatus.INACTIVE
    await db.flush()


@router.get("/{node_id}/capacity", response_model=dict)
async def get_node_capacity(node_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FulfillmentNode).where(FulfillmentNode.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return {
        "node_id": str(node.id),
        "daily_capacity": node.daily_order_capacity,
        "current_orders": node.current_daily_orders,
        "available_capacity": node.daily_order_capacity - node.current_daily_orders,
        "utilization_pct": round(node.current_daily_orders / max(node.daily_order_capacity, 1) * 100, 2),
    }
