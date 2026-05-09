"""Analytics router — dashboard metrics and reporting."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case, and_
from typing import Optional
from datetime import datetime, timedelta, date

from app.database.postgres import get_db
from app.dependencies.auth import get_current_user, require_superadmin
from app.models.postgres.order_models import Order, OrderStatus, FulfillmentAllocation
from app.models.postgres.node_models import FulfillmentNode
from app.models.postgres.inventory_models import InventoryItem
from app.models.postgres.brand_models import Brand
from app.schemas.analytics import (
    DashboardSummary, ChannelBreakdown, FulfillmentTypeBreakdown,
    NodePerformanceMetric, SourcingStrategyMetric, OrderVolumeMetric,
    OrderTypeBreakdown,
)

router = APIRouter(prefix="/analytics", tags=["Analytics"], dependencies=[Depends(get_current_user)])


@router.get("/dashboard", response_model=DashboardSummary)
async def get_dashboard(
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    brand_id: Optional[str] = Query(default=None),
    channel: Optional[str] = Query(default=None),
    order_type: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # Default: last 30 days
    if not to_date:
        to_date = date.today()
    if not from_date:
        from_date = to_date - timedelta(days=30)

    from_dt = datetime.combine(from_date, datetime.min.time())
    to_dt = datetime.combine(to_date, datetime.max.time())

    effective_brand_id = brand_id if current_user.get("is_superadmin") else None

    def _base_filters():
        conditions = [Order.created_at.between(from_dt, to_dt)]
        if effective_brand_id:
            conditions.append(Order.brand_id == effective_brand_id)
        if channel:
            conditions.append(Order.channel == channel)
        if order_type:
            conditions.append(Order.order_type == order_type)
        return conditions

    def _brand_filter():
        return _base_filters()

    # Total orders and revenue
    total_result = await db.execute(
        select(
            func.count(Order.id).label("count"),
            func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
        ).where(*_brand_filter())
    )
    totals = total_result.one()
    total_orders = totals.count
    total_revenue = float(totals.revenue)
    avg_order_value = round(total_revenue / max(total_orders, 1), 2)

    # Orders by status
    status_result = await db.execute(
        select(Order.status, func.count(Order.id).label("count"))
        .where(*_brand_filter())
        .group_by(Order.status)
    )
    orders_by_status = {row.status.value: row.count for row in status_result.all()}

    # Orders by channel
    channel_result = await db.execute(
        select(
            Order.channel,
            func.count(Order.id).label("count"),
            func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
        )
        .where(*_brand_filter())
        .group_by(Order.channel)
    )
    channel_rows = channel_result.all()
    orders_by_channel = [
        ChannelBreakdown(
            channel=r.channel.value,
            count=r.count,
            percentage=round(r.count / max(total_orders, 1) * 100, 2),
            total_revenue=float(r.revenue),
        )
        for r in channel_rows
    ]

    # Orders by fulfillment type
    ft_result = await db.execute(
        select(
            Order.fulfillment_type,
            func.count(Order.id).label("count"),
        )
        .where(*_brand_filter())
        .group_by(Order.fulfillment_type)
    )
    ft_rows = ft_result.all()
    orders_by_ft = [
        FulfillmentTypeBreakdown(
            fulfillment_type=r.fulfillment_type.value,
            count=r.count,
            percentage=round(r.count / max(total_orders, 1) * 100, 2),
            avg_processing_hours=24.0,  # placeholder
        )
        for r in ft_rows
    ]

    # Top nodes by allocations
    node_result = await db.execute(
        select(
            FulfillmentNode.id,
            FulfillmentNode.name,
            FulfillmentNode.code,
            FulfillmentNode.daily_order_capacity,
            FulfillmentNode.current_daily_orders,
            func.count(FulfillmentAllocation.id).label("allocation_count"),
        )
        .join(FulfillmentAllocation, FulfillmentAllocation.node_id == FulfillmentNode.id, isouter=True)
        .group_by(FulfillmentNode.id)
        .order_by(func.count(FulfillmentAllocation.id).desc())
        .limit(10)
    )
    top_nodes = [
        NodePerformanceMetric(
            node_id=str(r.id),
            node_name=r.name,
            node_code=r.code,
            total_orders=r.current_daily_orders,
            total_allocations=r.allocation_count,
            avg_processing_hours=24.0,
            capacity_utilization=round(r.current_daily_orders / max(r.daily_order_capacity, 1) * 100, 2),
        )
        for r in node_result.all()
    ]

    # Orders by order type (RETAIL / WHOLESALE / B2B)
    order_type_result = await db.execute(
        select(
            Order.order_type,
            func.count(Order.id).label("count"),
            func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
        )
        .where(*_brand_filter())
        .group_by(Order.order_type)
    )
    orders_by_otype = [
        OrderTypeBreakdown(
            order_type=r.order_type or "RETAIL",
            count=r.count,
            percentage=round(r.count / max(total_orders, 1) * 100, 2),
            total_revenue=float(r.revenue),
        )
        for r in order_type_result.all()
    ]

    # Inventory alerts (low stock)
    low_stock_result = await db.execute(
        select(InventoryItem, FulfillmentNode)
        .join(FulfillmentNode, InventoryItem.node_id == FulfillmentNode.id)
        .where(
            InventoryItem.quantity_available <= InventoryItem.reorder_point,
            InventoryItem.is_active == True,
        )
        .limit(20)
    )
    inventory_alerts = [
        {
            "sku": inv.sku,
            "node": node.code,
            "available": inv.quantity_available,
            "reorder_point": inv.reorder_point,
        }
        for inv, node in low_stock_result.all()
    ]

    return DashboardSummary(
        period_start=from_dt.isoformat(),
        period_end=to_dt.isoformat(),
        total_orders=total_orders,
        total_revenue=total_revenue,
        avg_order_value=avg_order_value,
        orders_by_status=orders_by_status,
        orders_by_channel=orders_by_channel,
        orders_by_fulfillment_type=orders_by_ft,
        orders_by_order_type=orders_by_otype,
        top_nodes=top_nodes,
        sourcing_strategies=[],
        inventory_alerts=inventory_alerts,
    )


@router.get("/orders/volume", response_model=list)
async def get_order_volume(
    days: int = Query(default=30, ge=1, le=365),
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    brand_id: Optional[str] = Query(default=None),
    channel: Optional[str] = Query(default=None),
    order_type: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if from_date and to_date:
        from_dt = datetime.combine(from_date, datetime.min.time())
        to_dt = datetime.combine(to_date, datetime.max.time())
        filters = [Order.created_at.between(from_dt, to_dt)]
    else:
        from_dt = datetime.utcnow() - timedelta(days=days)
        filters = [Order.created_at >= from_dt]
    if brand_id and current_user.get("is_superadmin"):
        filters.append(Order.brand_id == brand_id)
    if channel:
        filters.append(Order.channel == channel)
    if order_type:
        filters.append(Order.order_type == order_type)
    result = await db.execute(
        select(
            func.date(Order.created_at).label("date"),
            func.count(Order.id).label("count"),
            func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
        )
        .where(*filters)
        .group_by(func.date(Order.created_at))
        .order_by(func.date(Order.created_at).asc())
    )
    rows = result.all()
    return [
        {
            "date": str(r.date),
            "count": r.count,
            "total_revenue": float(r.revenue),
            "avg_order_value": round(float(r.revenue) / max(r.count, 1), 2),
        }
        for r in rows
    ]


@router.get("/inventory/summary", response_model=dict)
async def get_inventory_summary(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(
            func.count(InventoryItem.id).label("total_skus"),
            func.sum(InventoryItem.quantity_on_hand).label("total_on_hand"),
            func.sum(InventoryItem.quantity_available).label("total_available"),
            func.sum(InventoryItem.quantity_reserved).label("total_reserved"),
            func.sum(
                case((InventoryItem.quantity_available <= InventoryItem.reorder_point, 1), else_=0)
            ).label("low_stock_count"),
        ).where(InventoryItem.is_active == True)
    )
    row = result.one()
    return {
        "total_skus": row.total_skus or 0,
        "total_on_hand": row.total_on_hand or 0,
        "total_available": row.total_available or 0,
        "total_reserved": row.total_reserved or 0,
        "low_stock_count": row.low_stock_count or 0,
    }
