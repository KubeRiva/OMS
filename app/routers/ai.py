"""AI Assistant router — KubeAI-powered OMS intelligence with streaming SSE."""
import json
import os
import logging
from typing import AsyncGenerator
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.dependencies.auth import get_current_user, require_superadmin

limiter = Limiter(key_func=get_remote_address)
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from app.database.postgres import async_session_factory
from app.models.postgres.order_models import (
    Order, OrderItem, FulfillmentAllocation, Shipment,
    OrderStatus, OrderChannel, FulfillmentType,
)
from app.models.postgres.inventory_models import InventoryItem
from app.models.postgres.node_models import FulfillmentNode
from app.models.postgres.sourcing_rule_models import SourcingRule

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["AI Assistant"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    session_id: str | None = None


# ─── Tool Definitions ─────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "search_orders",
        "description": (
            "Search and filter orders from the OMS database. "
            "Returns order details including status, customer, items, amounts, timestamps. "
            "Use this to find orders by status, channel, customer, date range, or general search."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by order status (e.g. PENDING, SHIPPED, DELIVERED)"},
                "channel": {"type": "string", "description": "Filter by channel (WEB, MOBILE, POS, API, MARKETPLACE)"},
                "customer_email": {"type": "string", "description": "Filter by customer email (partial match)"},
                "start_date": {"type": "string", "description": "Filter orders created on or after this date (ISO 8601, e.g. 2026-03-20 or 2026-03-20T00:00:00). Use today's date for 'today' queries."},
                "end_date": {"type": "string", "description": "Filter orders created on or before this date (ISO 8601, e.g. 2026-03-20T23:59:59). Use today's date for 'today' queries."},
                "limit": {"type": "integer", "description": "Number of orders to return (default 10, max 50)"},
                "order_by": {"type": "string", "description": "Sort field: created_at, total_amount (default: created_at desc)"},
            },
        },
    },
    {
        "name": "get_order_details",
        "description": "Get full details of a specific order by ID or order number, including line items, allocations, and shipments.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "The order UUID or order number (e.g. ORD-20240101-ABCDE)"},
            },
            "required": ["order_id"],
        },
    },
    {
        "name": "get_inventory_status",
        "description": "Get current inventory levels across all nodes. Can filter by SKU or node. Identifies low stock and out-of-stock items.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sku": {"type": "string", "description": "Filter by SKU (partial match)"},
                "node_id": {"type": "string", "description": "Filter by node UUID"},
                "low_stock_only": {"type": "boolean", "description": "Return only items below reorder point"},
                "limit": {"type": "integer", "description": "Max items to return (default 20)"},
            },
        },
    },
    {
        "name": "get_analytics_summary",
        "description": "Get OMS analytics: order counts by status/channel, revenue, top nodes, inventory alerts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Lookback period in days (default 30)"},
            },
        },
    },
    {
        "name": "get_sourcing_rules",
        "description": "Get all sourcing rules with their priorities, strategies, and conditions. Useful for analyzing sourcing configuration.",
        "input_schema": {
            "type": "object",
            "properties": {
                "active_only": {"type": "boolean", "description": "Return only active rules (default true)"},
            },
        },
    },
    {
        "name": "get_nodes",
        "description": "Get fulfillment nodes (warehouses, stores, dark stores) with their capacity and utilization.",
        "input_schema": {
            "type": "object",
            "properties": {
                "node_type": {"type": "string", "description": "Filter by type: WAREHOUSE, STORE, DARK_STORE"},
                "active_only": {"type": "boolean", "description": "Return only active nodes"},
            },
        },
    },
    {
        "name": "get_top_selling_items",
        "description": (
            "Get the best-selling / top-selling products ranked by units sold or revenue. "
            "Use this whenever the user asks about best sellers, top products, most popular items, "
            "top SKUs, or which products sell the most. Returns SKU, product name, total units sold, "
            "and total revenue, ranked from highest to lowest."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of top items to return (default 10, max 50)"},
                "days": {"type": "integer", "description": "Lookback period in days (default 30, 0 = all time)"},
                "rank_by": {"type": "string", "description": "Rank by 'quantity' (units sold) or 'revenue' (default: quantity)"},
            },
        },
    },
    {
        "name": "aggregate_orders",
        "description": (
            "Flexible aggregation query for any cross-dimensional analysis of orders. "
            "Use this for: top customers, revenue/orders by channel, daily/weekly/monthly trends, "
            "which fulfillment nodes handle the most orders, slowest-moving products, "
            "order value distributions, or any question requiring grouping and counting. "
            "Returns rows with a label, primary value, and secondary value for each group."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "group_by": {
                    "type": "string",
                    "description": (
                        "Dimension to group by. Options: "
                        "'sku' (product performance), "
                        "'customer' (top/bottom customers), "
                        "'channel' (WEB/MOBILE/POS/API/MARKETPLACE breakdown), "
                        "'status' (order status breakdown), "
                        "'node' (fulfillment node performance), "
                        "'day' (daily trend), "
                        "'week' (weekly trend), "
                        "'month' (monthly trend)"
                    ),
                },
                "metric": {
                    "type": "string",
                    "description": "What to measure: 'order_count' (default), 'revenue', 'quantity' (units sold, only for group_by=sku)",
                },
                "sort_order": {
                    "type": "string",
                    "description": "'desc' for highest first (default), 'asc' for lowest first (use for slow-movers, least active customers, etc.)",
                },
                "days": {"type": "integer", "description": "Lookback period in days (default 30, 0 = all time)"},
                "limit": {"type": "integer", "description": "Max rows to return (default 10, max 50)"},
                "filter_status": {"type": "string", "description": "Optional: filter to a specific order status before aggregating"},
                "filter_channel": {"type": "string", "description": "Optional: filter to a specific channel before aggregating"},
            },
            "required": ["group_by"],
        },
    },
]


# ─── Tool Execution ───────────────────────────────────────────────────────────

async def execute_tool(tool_name: str, tool_input: dict) -> dict:
    """Execute a tool and return structured data."""
    async with async_session_factory() as db:
        if tool_name == "search_orders":
            return await _search_orders(db, tool_input)
        elif tool_name == "get_order_details":
            return await _get_order_details(db, tool_input)
        elif tool_name == "get_inventory_status":
            return await _get_inventory_status(db, tool_input)
        elif tool_name == "get_analytics_summary":
            return await _get_analytics_summary(db, tool_input)
        elif tool_name == "get_sourcing_rules":
            return await _get_sourcing_rules(db, tool_input)
        elif tool_name == "get_nodes":
            return await _get_nodes(db, tool_input)
        elif tool_name == "get_top_selling_items":
            return await _get_top_selling_items(db, tool_input)
        elif tool_name == "aggregate_orders":
            return await _aggregate_orders(db, tool_input)
        else:
            return {"error": f"Unknown tool: {tool_name}"}


async def _search_orders(db, inp: dict) -> dict:
    q = select(Order).options(
        selectinload(Order.line_items),
        selectinload(Order.fulfillment_allocations),
        selectinload(Order.shipments),
    )
    if inp.get("status"):
        try:
            q = q.where(Order.status == OrderStatus(inp["status"].upper()))
        except ValueError:
            pass
    if inp.get("channel"):
        try:
            q = q.where(Order.channel == OrderChannel(inp["channel"].upper()))
        except ValueError:
            pass
    if inp.get("customer_email"):
        q = q.where(Order.customer_email.ilike(f"%{inp['customer_email']}%"))
    if inp.get("start_date"):
        try:
            from datetime import datetime
            start = datetime.fromisoformat(inp["start_date"].replace("Z", "+00:00"))
            q = q.where(Order.created_at >= start)
        except ValueError:
            pass
    if inp.get("end_date"):
        try:
            from datetime import datetime
            end = datetime.fromisoformat(inp["end_date"].replace("Z", "+00:00"))
            q = q.where(Order.created_at <= end)
        except ValueError:
            pass
    limit = min(int(inp.get("limit", 10)), 50)
    q = q.order_by(Order.created_at.desc()).limit(limit)
    result = await db.execute(q)
    orders = result.scalars().unique().all()
    return {"orders": [_order_to_dict(o) for o in orders], "count": len(orders)}


async def _get_order_details(db, inp: dict) -> dict:
    order_id = inp.get("order_id", "")
    q = select(Order).options(
        selectinload(Order.line_items),
        selectinload(Order.fulfillment_allocations),
        selectinload(Order.shipments),
    )
    # Try as order_number first (format: ORD-*)
    if order_id.upper().startswith("ORD-"):
        q = q.where(Order.order_number == order_id.upper())
    else:
        try:
            import uuid
            q = q.where(Order.id == uuid.UUID(order_id))
        except ValueError:
            q = q.where(Order.order_number.ilike(f"%{order_id}%"))
    result = await db.execute(q)
    order = result.scalars().unique().first()
    if not order:
        return {"error": f"Order '{order_id}' not found"}
    return {"order": _order_to_dict(order)}


async def _get_inventory_status(db, inp: dict) -> dict:
    q = select(InventoryItem, FulfillmentNode).join(
        FulfillmentNode, InventoryItem.node_id == FulfillmentNode.id
    )
    if inp.get("sku"):
        q = q.where(InventoryItem.sku.ilike(f"%{inp['sku']}%"))
    if inp.get("node_id"):
        try:
            import uuid
            q = q.where(InventoryItem.node_id == uuid.UUID(inp["node_id"]))
        except ValueError:
            pass
    if inp.get("low_stock_only"):
        q = q.where(InventoryItem.quantity_available <= InventoryItem.reorder_point)
    limit = min(int(inp.get("limit", 20)), 100)
    q = q.order_by(InventoryItem.quantity_available.asc()).limit(limit)
    result = await db.execute(q)
    rows = result.all()
    items = []
    for inv, node in rows:
        items.append({
            "id": str(inv.id),
            "sku": inv.sku,
            "product_name": inv.product_name,
            "node_id": str(inv.node_id),
            "node_name": node.name,
            "node_type": node.node_type.value if hasattr(node.node_type, "value") else str(node.node_type),
            "quantity_on_hand": inv.quantity_on_hand,
            "quantity_reserved": inv.quantity_reserved,
            "quantity_available": inv.quantity_available,
            "reorder_point": inv.reorder_point,
            "is_low_stock": inv.quantity_available <= inv.reorder_point,
            "unit_cost": float(inv.unit_cost) if inv.unit_cost else 0,
        })
    return {"inventory": items, "count": len(items)}


async def _get_analytics_summary(db, inp: dict) -> dict:
    from datetime import datetime, timedelta
    days = int(inp.get("days", 30))
    since = datetime.utcnow() - timedelta(days=days)

    # Order counts by status
    status_q = (
        select(Order.status, func.count(Order.id).label("cnt"))
        .where(Order.created_at >= since)
        .group_by(Order.status)
    )
    status_result = await db.execute(status_q)
    by_status = {r.status.value: r.cnt for r in status_result}

    # Revenue + count
    rev_q = (
        select(func.count(Order.id).label("cnt"), func.sum(Order.total_amount).label("rev"))
        .where(Order.created_at >= since)
    )
    rev_result = await db.execute(rev_q)
    rev_row = rev_result.first()
    total_orders = int(rev_row.cnt or 0)
    total_revenue = float(rev_row.rev or 0)

    # Channel breakdown
    ch_q = (
        select(Order.channel, func.count(Order.id).label("cnt"))
        .where(Order.created_at >= since)
        .group_by(Order.channel)
    )
    ch_result = await db.execute(ch_q)
    by_channel = {r.channel.value: r.cnt for r in ch_result}

    # Low stock alerts
    low_stock_q = (
        select(func.count(InventoryItem.id))
        .where(InventoryItem.quantity_available <= InventoryItem.reorder_point)
        .where(InventoryItem.is_active == True)
    )
    low_stock_result = await db.execute(low_stock_q)
    low_stock_count = low_stock_result.scalar() or 0

    # Active nodes
    node_q = select(func.count(FulfillmentNode.id)).where(FulfillmentNode.status == "ACTIVE")
    node_result = await db.execute(node_q)
    active_nodes = node_result.scalar() or 0

    return {
        "period_days": days,
        "total_orders": total_orders,
        "total_revenue": round(total_revenue, 2),
        "avg_order_value": round(total_revenue / total_orders, 2) if total_orders else 0,
        "orders_by_status": by_status,
        "orders_by_channel": by_channel,
        "low_stock_alerts": int(low_stock_count),
        "active_nodes": int(active_nodes),
    }


async def _get_sourcing_rules(db, inp: dict) -> dict:
    q = select(SourcingRule)
    if inp.get("active_only", True):
        q = q.where(SourcingRule.is_active == True)
    q = q.order_by(SourcingRule.priority.asc())
    result = await db.execute(q)
    rules = result.scalars().all()
    return {
        "rules": [
            {
                "id": str(r.id),
                "name": r.name,
                "priority": r.priority,
                "is_active": r.is_active,
                "strategy": r.strategy.value if hasattr(r.strategy, "value") else str(r.strategy),
                "conditions": r.conditions or [],
                "allowed_node_types": r.allowed_node_types or [],
                "required_capabilities": r.required_capabilities or [],
                "max_split_nodes": r.max_split_nodes,
                "cost_weight": float(r.cost_weight or 0),
                "distance_weight": float(r.distance_weight or 0),
            }
            for r in rules
        ],
        "count": len(rules),
    }


async def _get_nodes(db, inp: dict) -> dict:
    q = select(FulfillmentNode)
    if inp.get("node_type"):
        q = q.where(FulfillmentNode.node_type == inp["node_type"].upper())
    if inp.get("active_only", True):
        q = q.where(FulfillmentNode.status == "ACTIVE")
    result = await db.execute(q)
    nodes = result.scalars().all()
    return {
        "nodes": [
            {
                "id": str(n.id),
                "code": n.code,
                "name": n.name,
                "node_type": n.node_type.value if hasattr(n.node_type, "value") else str(n.node_type),
                "status": n.status.value if hasattr(n.status, "value") else str(n.status),
                "city": n.city,
                "state": n.state,
                "country": n.country,
                "daily_order_capacity": n.daily_order_capacity,
                "current_daily_orders": n.current_daily_orders,
                "capacity_utilization": round(
                    (n.current_daily_orders / n.daily_order_capacity * 100) if n.daily_order_capacity else 0, 1
                ),
                "can_ship": n.can_ship,
                "can_pickup": n.can_pickup,
                "can_same_day": n.can_same_day,
            }
            for n in nodes
        ],
        "count": len(nodes),
    }


async def _get_top_selling_items(db, inp: dict) -> dict:
    from datetime import datetime, timedelta
    limit = min(int(inp.get("limit", 10)), 50)
    days = int(inp.get("days", 30))
    rank_by = inp.get("rank_by", "quantity")

    q = (
        select(
            OrderItem.sku,
            OrderItem.product_name,
            func.sum(OrderItem.quantity).label("total_quantity"),
            func.sum(OrderItem.total_price).label("total_revenue"),
            func.count(func.distinct(OrderItem.order_id)).label("order_count"),
        )
        .group_by(OrderItem.sku, OrderItem.product_name)
    )

    if days > 0:
        since = datetime.utcnow() - timedelta(days=days)
        q = q.join(Order, OrderItem.order_id == Order.id).where(Order.created_at >= since)

    if rank_by == "revenue":
        q = q.order_by(func.sum(OrderItem.total_price).desc())
    else:
        q = q.order_by(func.sum(OrderItem.quantity).desc())

    q = q.limit(limit)
    result = await db.execute(q)
    rows = result.all()

    items = [
        {
            "sku": r.sku,
            "product_name": r.product_name or r.sku,
            "total_quantity": int(r.total_quantity or 0),
            "total_revenue": round(float(r.total_revenue or 0), 2),
            "order_count": int(r.order_count or 0),
        }
        for r in rows
    ]
    return {
        "items": items,
        "count": len(items),
        "period_days": days,
        "rank_by": rank_by,
    }


async def _aggregate_orders(db, inp: dict) -> dict:
    from datetime import datetime, timedelta
    group_by = inp.get("group_by", "status")
    metric = inp.get("metric", "order_count")
    sort_order = inp.get("sort_order", "desc")
    days = int(inp.get("days", 30))
    limit = min(int(inp.get("limit", 10)), 50)
    filter_status = inp.get("filter_status")
    filter_channel = inp.get("filter_channel")

    # Build common time/channel/status filters
    base_filters = []
    if days > 0:
        since = datetime.utcnow() - timedelta(days=days)
        base_filters.append(Order.created_at >= since)
    if filter_status:
        try:
            base_filters.append(Order.status == OrderStatus(filter_status.upper()))
        except ValueError:
            pass
    if filter_channel:
        try:
            base_filters.append(Order.channel == OrderChannel(filter_channel.upper()))
        except ValueError:
            pass

    rows = []
    group_label = group_by

    if group_by in ("sku", "product"):
        group_label = "product"
        qty_col = func.sum(OrderItem.quantity)
        rev_col = func.sum(OrderItem.total_price)
        sort_col = rev_col if metric == "revenue" else qty_col
        q = (
            select(
                OrderItem.sku,
                OrderItem.product_name,
                qty_col.label("qty"),
                rev_col.label("rev"),
                func.count(func.distinct(OrderItem.order_id)).label("orders"),
            )
            .join(Order, OrderItem.order_id == Order.id)
            .group_by(OrderItem.sku, OrderItem.product_name)
        )
        for f in base_filters:
            q = q.where(f)
        q = q.order_by(sort_col.asc() if sort_order == "asc" else sort_col.desc()).limit(limit)
        for r in (await db.execute(q)).all():
            rows.append({
                "label": r.product_name or r.sku,
                "sublabel": r.sku,
                "primary_value": int(r.qty or 0),
                "primary_label": "units",
                "secondary_value": round(float(r.rev or 0), 2),
                "secondary_label": "revenue",
                "count": int(r.orders or 0),
            })

    elif group_by == "customer":
        sort_col = func.sum(Order.total_amount) if metric == "revenue" else func.count(Order.id)
        q = (
            select(
                Order.customer_email,
                Order.customer_name,
                func.count(Order.id).label("order_count"),
                func.sum(Order.total_amount).label("revenue"),
            )
            .group_by(Order.customer_email, Order.customer_name)
        )
        for f in base_filters:
            q = q.where(f)
        q = q.order_by(sort_col.asc() if sort_order == "asc" else sort_col.desc()).limit(limit)
        for r in (await db.execute(q)).all():
            rows.append({
                "label": r.customer_name or r.customer_email,
                "sublabel": r.customer_email,
                "primary_value": round(float(r.revenue or 0), 2),
                "primary_label": "revenue",
                "secondary_value": int(r.order_count or 0),
                "secondary_label": "orders",
                "count": int(r.order_count or 0),
            })

    elif group_by == "channel":
        sort_col = func.sum(Order.total_amount) if metric == "revenue" else func.count(Order.id)
        q = (
            select(
                Order.channel,
                func.count(Order.id).label("order_count"),
                func.sum(Order.total_amount).label("revenue"),
            )
            .group_by(Order.channel)
        )
        for f in base_filters:
            q = q.where(f)
        q = q.order_by(sort_col.asc() if sort_order == "asc" else sort_col.desc())
        for r in (await db.execute(q)).all():
            ch = r.channel.value if hasattr(r.channel, "value") else str(r.channel)
            rows.append({
                "label": ch,
                "sublabel": None,
                "primary_value": int(r.order_count or 0),
                "primary_label": "orders",
                "secondary_value": round(float(r.revenue or 0), 2),
                "secondary_label": "revenue",
                "count": int(r.order_count or 0),
            })

    elif group_by == "status":
        sort_col = func.sum(Order.total_amount) if metric == "revenue" else func.count(Order.id)
        q = (
            select(
                Order.status,
                func.count(Order.id).label("order_count"),
                func.sum(Order.total_amount).label("revenue"),
            )
            .group_by(Order.status)
        )
        for f in base_filters:
            q = q.where(f)
        q = q.order_by(sort_col.asc() if sort_order == "asc" else sort_col.desc())
        for r in (await db.execute(q)).all():
            st = r.status.value if hasattr(r.status, "value") else str(r.status)
            rows.append({
                "label": st,
                "sublabel": None,
                "primary_value": int(r.order_count or 0),
                "primary_label": "orders",
                "secondary_value": round(float(r.revenue or 0), 2),
                "secondary_label": "revenue",
                "count": int(r.order_count or 0),
            })

    elif group_by in ("day", "week", "month"):
        trunc = group_by
        trunc_expr = func.date_trunc(trunc, Order.created_at)
        sort_col = func.sum(Order.total_amount) if metric == "revenue" else func.count(Order.id)
        q = (
            select(
                trunc_expr.label("period"),
                func.count(Order.id).label("order_count"),
                func.sum(Order.total_amount).label("revenue"),
            )
            .group_by(trunc_expr)
        )
        for f in base_filters:
            q = q.where(f)
        # Time series: order by period asc so it reads chronologically
        q = q.order_by(trunc_expr.asc()).limit(limit)
        for r in (await db.execute(q)).all():
            period_str = r.period.strftime("%Y-%m-%d") if r.period else "unknown"
            rows.append({
                "label": period_str,
                "sublabel": None,
                "primary_value": int(r.order_count or 0),
                "primary_label": "orders",
                "secondary_value": round(float(r.revenue or 0), 2),
                "secondary_label": "revenue",
                "count": int(r.order_count or 0),
            })

    elif group_by == "node":
        sort_col = func.count(func.distinct(FulfillmentAllocation.order_id))
        q = (
            select(
                FulfillmentNode.name,
                FulfillmentNode.code,
                FulfillmentNode.node_type,
                func.count(func.distinct(FulfillmentAllocation.order_id)).label("order_count"),
                func.count(FulfillmentAllocation.id).label("allocation_count"),
            )
            .join(FulfillmentNode, FulfillmentAllocation.node_id == FulfillmentNode.id)
            .join(Order, FulfillmentAllocation.order_id == Order.id)
            .group_by(FulfillmentNode.name, FulfillmentNode.code, FulfillmentNode.node_type)
        )
        for f in base_filters:
            q = q.where(f)
        q = q.order_by(sort_col.asc() if sort_order == "asc" else sort_col.desc()).limit(limit)
        for r in (await db.execute(q)).all():
            nt = r.node_type.value if hasattr(r.node_type, "value") else str(r.node_type)
            rows.append({
                "label": r.name,
                "sublabel": f"{r.code} · {nt}",
                "primary_value": int(r.order_count or 0),
                "primary_label": "orders",
                "secondary_value": int(r.allocation_count or 0),
                "secondary_label": "allocations",
                "count": int(r.order_count or 0),
            })

    return {
        "group_by": group_label,
        "metric": metric,
        "sort_order": sort_order,
        "period_days": days,
        "rows": rows,
        "count": len(rows),
    }


def _order_to_dict(o: Order) -> dict:
    return {
        "id": str(o.id),
        "order_number": o.order_number,
        "status": o.status.value if o.status else None,
        "channel": o.channel.value if o.channel else None,
        "fulfillment_type": o.fulfillment_type.value if o.fulfillment_type else None,
        "customer_email": o.customer_email,
        "customer_name": o.customer_name,
        "total_amount": float(o.total_amount or 0),
        "currency": o.currency,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
        "confirmed_at": o.confirmed_at.isoformat() if o.confirmed_at else None,
        "delivered_at": o.delivered_at.isoformat() if o.delivered_at else None,
        "cancelled_at": o.cancelled_at.isoformat() if o.cancelled_at else None,
        "shipping_city": o.shipping_city,
        "shipping_state": o.shipping_state,
        "shipping_country": o.shipping_country,
        "payment_status": o.payment_status.value if o.payment_status else None,
        "line_items": [
            {
                "sku": i.sku,
                "product_name": i.product_name,
                "quantity": i.quantity,
                "quantity_fulfilled": i.quantity_fulfilled,
                "unit_price": float(i.unit_price or 0),
                "total_price": float(i.total_price or 0),
            }
            for i in (o.line_items or [])
        ],
        "shipments": [
            {
                "tracking_number": s.tracking_number,
                "carrier": s.carrier,
                "status": s.status.value if hasattr(s.status, "value") else str(s.status),
                "shipped_at": s.shipped_at.isoformat() if s.shipped_at else None,
                "estimated_delivery_at": s.estimated_delivery_at.isoformat() if s.estimated_delivery_at else None,
            }
            for s in (o.shipments or [])
        ],
    }


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _data_kind(tool_name: str, result: dict) -> str | None:
    """Map a tool name to the frontend rich-data kind, or None to skip rendering."""
    if tool_name == "search_orders" and "orders" in result:
        return "orders"
    if tool_name == "get_order_details" and "order" in result:
        return "order_detail"
    if tool_name == "get_inventory_status" and "inventory" in result:
        return "inventory"
    if tool_name == "get_analytics_summary":
        return "analytics"
    if tool_name == "get_nodes":
        return "nodes"
    if tool_name == "get_sourcing_rules":
        return "sourcing"
    if tool_name == "get_top_selling_items":
        return "top_items"
    if tool_name == "aggregate_orders":
        return "aggregate"
    return None


# ─── SSE Streaming Generator ──────────────────────────────────────────────────

async def _stream_ai_response(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Agentic loop: stream KubeAI tokens in real-time, execute tools between rounds."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        yield f"data: {json.dumps({'type': 'error', 'message': 'ANTHROPIC_API_KEY not configured'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
    except ImportError:
        yield f"data: {json.dumps({'type': 'error', 'message': 'anthropic package not installed'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    from datetime import datetime, timezone
    _now = datetime.now(timezone.utc)
    _today_str = _now.strftime("%Y-%m-%d")
    _today_start = f"{_today_str}T00:00:00"
    _today_end = f"{_today_str}T23:59:59"

    system_prompt = f"""You are an intelligent OMS (Order Management System) assistant. You have live access to order, inventory, and fulfillment data through tools. Always query the data before answering — never guess.

TODAY'S DATE: {_today_str} (UTC). When the user says "today", use start_date="{_today_start}" and end_date="{_today_end}" in search_orders. When they say "this week" use start_date 7 days ago. "This month" = start of current month.

═══ TOOL SELECTION — FOLLOW THIS STRICTLY ═══

UNDERSTAND the user's intent, then pick the correct tool:

1. "best selling", "top products", "most popular", "what sells most", "best seller"
   → get_top_selling_items

2. "worst selling", "slow movers", "least popular", "what doesn't sell"
   → get_top_selling_items with rank_by=quantity (data is already there, just lowest values)
   OR aggregate_orders(group_by="sku", sort_order="asc")

3. "top customers", "who spends most", "best customers", "loyal customers"
   → aggregate_orders(group_by="customer", metric="revenue", sort_order="desc")

4. "revenue by channel", "channel breakdown", "which channel performs best"
   → aggregate_orders(group_by="channel", metric="revenue")

5. "daily/weekly/monthly trends", "orders over time", "revenue trend", "how many orders per day"
   → aggregate_orders(group_by="day" or "week" or "month")

6. "which node fulfills most", "busiest warehouse", "node performance"
   → aggregate_orders(group_by="node")

7. "overall summary", "total stats", "how many orders total", "revenue this month"
   → get_analytics_summary

8. "find order ORD-...", "order for customer@email.com", "show pending orders"
   → search_orders or get_order_details

9. "stock levels", "inventory", "how many units of SKU-X", "low stock"
   → get_inventory_status

10. "sourcing rules", "how are orders routed"
    → get_sourcing_rules

11. "node locations", "fulfillment centers", "warehouse capacity"
    → get_nodes

CRITICAL: Do NOT use get_analytics_summary for product, customer, or trend questions. It only returns totals — use aggregate_orders for breakdowns.

═══ RESPONSE STYLE ═══
- Always cite specific numbers from the data
- Be concise: state the finding, then add 1-2 lines of expert insight
- If multiple tools are needed to fully answer, call them in sequence"""

    conversation = list(messages)
    max_rounds = 8

    try:
        for _round in range(max_rounds):
            # ── Track tool calls being assembled during streaming ──────────────
            tool_calls: list[dict] = []
            _cur_tool: dict | None = None
            _cur_input_json = ""

            async with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                system=system_prompt,
                tools=TOOLS,
                messages=conversation,
            ) as stream:
                async for event in stream:
                    etype = event.type

                    if etype == "content_block_start":
                        cb = event.content_block
                        if cb.type == "tool_use":
                            _cur_tool = {"id": cb.id, "name": cb.name}
                            _cur_input_json = ""
                            # Emit badge immediately so the UI shows activity
                            yield f"data: {json.dumps({'type': 'tool_call', 'tool': cb.name})}\n\n"
                        else:
                            _cur_tool = None

                    elif etype == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            # Stream tokens to the frontend in real-time
                            yield f"data: {json.dumps({'type': 'text_delta', 'text': delta.text})}\n\n"
                        elif delta.type == "input_json_delta" and _cur_tool is not None:
                            _cur_input_json += delta.partial_json

                    elif etype == "content_block_stop":
                        if _cur_tool is not None:
                            try:
                                _cur_tool["input"] = json.loads(_cur_input_json) if _cur_input_json else {}
                            except Exception:
                                _cur_tool["input"] = {}
                            tool_calls.append(_cur_tool)
                            _cur_tool = None
                            _cur_input_json = ""

                # final_message has the complete, properly typed content
                final_msg = await stream.get_final_message()

            # No tool calls → final text was already streamed token-by-token; done
            if not tool_calls:
                break

            # ── Serialize assistant turn to plain dicts for the next API call ──
            # Passing raw SDK objects back causes a serialization error on round 2
            assistant_content = []
            for blk in final_msg.content:
                if blk.type == "text":
                    assistant_content.append({"type": "text", "text": blk.text})
                elif blk.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": blk.id,
                        "name": blk.name,
                        "input": blk.input,
                    })
            conversation.append({"role": "assistant", "content": assistant_content})

            # ── Execute tools, emit data cards, collect results ────────────────
            tool_results = []
            for tc in tool_calls:
                try:
                    result = await execute_tool(tc["name"], tc["input"])
                    kind = _data_kind(tc["name"], result)
                    if kind:
                        yield f"data: {json.dumps({'type': 'data', 'kind': kind, 'data': result})}\n\n"
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc["id"],
                        "content": json.dumps(result),
                    })
                except Exception as exc:
                    logger.exception(f"Tool {tc['name']} failed")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc["id"],
                        "content": json.dumps({"error": "Tool execution failed"}),
                    })

            conversation.append({"role": "user", "content": tool_results})

    except Exception as exc:
        logger.exception("AI streaming error")
        yield f"data: {json.dumps({'type': 'error', 'message': 'An error occurred processing your request'})}\n\n"

    yield "data: [DONE]\n\n"


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/chat")
@limiter.limit("30/minute")
async def ai_chat(request: Request, body: ChatRequest, _: dict = Depends(get_current_user)):
    """Stream AI assistant response with tool use."""
    messages = [{"role": m.role, "content": m.content} for m in body.messages]
    return StreamingResponse(
        _stream_ai_response(messages),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/status")
async def ai_status(_: dict = Depends(require_superadmin)):
    """Check AI configuration status."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    has_key = bool(api_key and len(api_key) > 10)
    try:
        import anthropic  # noqa: F401
        has_package = True
    except ImportError:
        has_package = False
    status_value = "ok" if (has_key and has_package) else "unavailable"
    return {
        "status": status_value,
        "model": "claude-sonnet-4-6",
    }
