"""
demo_seed.py — Demo environment seed script for KubeRiva OMS

Creates a realistic demo environment:
  • 3 fulfillment nodes (Chicago near capacity, SF Warehouse, NYC DC)
  • 12 SKUs spread unevenly across nodes
  • 5 sourcing rules
  • 12 orders across all fulfillment types and statuses
  • 150+ MongoDB sourcing outcomes so AI Architect has real pattern data
  • Node performance metrics in MongoDB

Usage:
  python scripts/demo_seed.py

Requires DATABASE_URL / SYNC_DATABASE_URL and MONGODB_URL in environment.
Run from repo root: docker compose exec api python scripts/demo_seed.py
"""

import asyncio
import os
import uuid
import random
from datetime import datetime, timezone, timedelta
from decimal import Decimal

# ── SQLAlchemy (async) ──────────────────────────────────────────────────────
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, delete

# ── Models — import ALL so SQLAlchemy resolves all FK relationships ──────────
from app.models.postgres.node_models import FulfillmentNode, NodeType, NodeStatus
from app.models.postgres.inventory_models import InventoryItem, InventoryAdjustment, InventoryAdjustmentReason
from app.models.postgres.order_models import (
    Order, OrderItem, FulfillmentAllocation,
    OrderChannel, FulfillmentType, OrderStatus, OrderItemStatus, PaymentStatus,
    AllocationStatus,
)
from app.models.postgres.sourcing_rule_models import SourcingRule
import app.models.postgres.connector_models   # noqa: F401 — needed for FK resolution
import app.models.postgres.auth_models        # noqa: F401
import app.models.postgres.org_models         # noqa: F401
import app.models.postgres.lifecycle_models   # noqa: F401
import app.models.postgres.ai_models          # noqa: F401

# ── MongoDB ──────────────────────────────────────────────────────────────────
from motor.motor_asyncio import AsyncIOMotorClient

# ── Config ───────────────────────────────────────────────────────────────────
from app.config import get_settings

settings = get_settings()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DEMO DATA DEFINITIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

NODES = [
    {
        "code": "CHI-STORE-01",
        "name": "Chicago Downtown Store",
        "node_type": NodeType.RETAIL_STORE,
        "status": NodeStatus.ACTIVE,
        "address_line1": "111 N State St",
        "city": "Chicago", "state": "IL", "postal_code": "60601", "country": "US",
        "latitude": 41.8827, "longitude": -87.6278,
        "can_ship": True, "can_pickup": True, "can_curbside": True, "can_same_day": True,
        "daily_order_capacity": 120,
        "current_daily_orders": 108,   # near capacity — key for stress test demo
        "avg_processing_hours": 2.0,
        "shipping_cost_multiplier": 1.1,
    },
    {
        "code": "SFO-WH-01",
        "name": "San Francisco Warehouse",
        "node_type": NodeType.DISTRIBUTION_CENTER,
        "status": NodeStatus.ACTIVE,
        "address_line1": "450 Mission Rock St",
        "city": "San Francisco", "state": "CA", "postal_code": "94158", "country": "US",
        "latitude": 37.7749, "longitude": -122.4194,
        "can_ship": True, "can_pickup": False, "can_curbside": False, "can_same_day": False,
        "daily_order_capacity": 800,
        "current_daily_orders": 312,
        "avg_processing_hours": 6.0,
        "shipping_cost_multiplier": 0.9,
    },
    {
        "code": "NYC-DC-01",
        "name": "New York Distribution Center",
        "node_type": NodeType.DISTRIBUTION_CENTER,
        "status": NodeStatus.ACTIVE,
        "address_line1": "1 Red Hook Lane",
        "city": "Brooklyn", "state": "NY", "postal_code": "11231", "country": "US",
        "latitude": 40.7128, "longitude": -74.0060,
        "can_ship": True, "can_pickup": False, "can_curbside": False, "can_same_day": True,
        "daily_order_capacity": 1000,
        "current_daily_orders": 420,
        "avg_processing_hours": 4.0,
        "shipping_cost_multiplier": 0.85,
    },
]

SKUS = [
    {"sku": "WGT-ALPHA-001", "name": "Widget Alpha",        "unit_cost": 12.50, "weight_lbs": 0.5},
    {"sku": "WGT-BETA-002",  "name": "Widget Beta",         "unit_cost": 24.99, "weight_lbs": 1.2},
    {"sku": "GAD-ULTRA-010", "name": "Gadget Ultra",        "unit_cost": 89.00, "weight_lbs": 2.0},
    {"sku": "GAD-MINI-011",  "name": "Gadget Mini",         "unit_cost": 34.50, "weight_lbs": 0.3},
    {"sku": "PRO-CASE-020",  "name": "Pro Carry Case",      "unit_cost": 18.00, "weight_lbs": 0.8},
    {"sku": "CBL-USB-C-030", "name": "USB-C Cable 6ft",     "unit_cost": 9.99,  "weight_lbs": 0.1},
    {"sku": "CBL-HDMI-031",  "name": "HDMI 4K Cable",       "unit_cost": 14.99, "weight_lbs": 0.2},
    {"sku": "PWR-BANK-040",  "name": "Power Bank 20000mAh", "unit_cost": 45.00, "weight_lbs": 1.1},
    {"sku": "DOCK-HUB-050",  "name": "7-in-1 USB Hub",      "unit_cost": 59.00, "weight_lbs": 0.6},
    {"sku": "SPKR-BT-060",   "name": "BT Speaker Compact",  "unit_cost": 79.00, "weight_lbs": 1.5},
    {"sku": "KBRD-MECH-070", "name": "Mech Keyboard TKL",   "unit_cost": 129.00,"weight_lbs": 2.4},
    {"sku": "MOUS-ERGO-080", "name": "Ergonomic Mouse",     "unit_cost": 49.00, "weight_lbs": 0.4},
]

# Inventory per node — CHI intentionally lower stock on popular SKUs
INVENTORY = {
    "CHI-STORE-01": {
        "WGT-ALPHA-001": 45,  "WGT-BETA-002": 12,  "GAD-ULTRA-010": 8,
        "GAD-MINI-011":  30,  "PRO-CASE-020": 22,  "CBL-USB-C-030": 80,
        "CBL-HDMI-031":  60,  "PWR-BANK-040": 5,   "DOCK-HUB-050":  18,
        "SPKR-BT-060":   7,   "KBRD-MECH-070": 4,  "MOUS-ERGO-080": 25,
    },
    "SFO-WH-01": {
        "WGT-ALPHA-001": 320, "WGT-BETA-002": 185, "GAD-ULTRA-010": 92,
        "GAD-MINI-011":  210, "PRO-CASE-020": 145, "CBL-USB-C-030": 500,
        "CBL-HDMI-031":  380, "PWR-BANK-040": 76,  "DOCK-HUB-050":  120,
        "SPKR-BT-060":   55,  "KBRD-MECH-070": 40, "MOUS-ERGO-080": 180,
    },
    "NYC-DC-01": {
        "WGT-ALPHA-001": 280, "WGT-BETA-002": 160, "GAD-ULTRA-010": 85,
        "GAD-MINI-011":  195, "PRO-CASE-020": 130, "CBL-USB-C-030": 450,
        "CBL-HDMI-031":  310, "PWR-BANK-040": 68,  "DOCK-HUB-050":  95,
        "SPKR-BT-060":   48,  "KBRD-MECH-070": 35, "MOUS-ERGO-080": 155,
    },
}

SOURCING_RULES = [
    {
        "name": "High-Value Orders → NYC DC",
        "description": "Orders over $200 routed to NYC DC for priority processing",
        "strategy": "COST_OPTIMAL",
        "priority": 1,
        "is_active": True,
        "conditions": [{"field": "total_amount", "operator": "GTE", "value": 200}],
        "required_capabilities": [],
        "allowed_node_types": ["DISTRIBUTION_CENTER"],
    },
    {
        "name": "Same-Day Delivery",
        "description": "Same-day orders go to nearest can_same_day node",
        "strategy": "STORE_NEAREST",
        "priority": 2,
        "is_active": True,
        "conditions": [{"field": "fulfillment_type", "operator": "EQ", "value": "SAME_DAY_DELIVERY"}],
        "required_capabilities": ["can_same_day"],
        "allowed_node_types": [],
    },
    {
        "name": "Distance Optimal — Web Channel",
        "description": "Web orders routed to nearest node with stock",
        "strategy": "DISTANCE_OPTIMAL",
        "priority": 3,
        "is_active": True,
        "conditions": [{"field": "channel", "operator": "EQ", "value": "WEB"}],
        "required_capabilities": [],
        "allowed_node_types": [],
    },
    {
        "name": "Marketplace — Least Cost Split",
        "description": "Marketplace orders use least cost split across nodes",
        "strategy": "LEAST_COST_SPLIT",
        "priority": 4,
        "is_active": True,
        "conditions": [{"field": "channel", "operator": "EQ", "value": "MARKETPLACE"}],
        "required_capabilities": [],
        "allowed_node_types": [],
    },
    {
        "name": "Default — Distance Optimal",
        "description": "Fallback: route to nearest node with stock",
        "strategy": "DISTANCE_OPTIMAL",
        "priority": 10,
        "is_active": True,
        "conditions": [],
        "required_capabilities": [],
        "allowed_node_types": [],
    },
]

CUSTOMERS = [
    {"name": "Sarah Johnson",  "email": "sarah.j@demo.com",   "city": "Chicago",      "state": "IL", "zip": "60601", "lat": 41.8827, "lng": -87.6278},
    {"name": "Michael Chen",   "email": "m.chen@demo.com",    "city": "San Francisco","state": "CA", "zip": "94102", "lat": 37.7749, "lng": -122.4194},
    {"name": "Priya Patel",    "email": "priya.p@demo.com",   "city": "New York",     "state": "NY", "zip": "10001", "lat": 40.7128, "lng": -74.0060},
    {"name": "James Williams", "email": "j.williams@demo.com","city": "Austin",       "state": "TX", "zip": "78701", "lat": 30.2672, "lng": -97.7431},
    {"name": "Emma Davis",     "email": "emma.d@demo.com",    "city": "Seattle",      "state": "WA", "zip": "98101", "lat": 47.6062, "lng": -122.3321},
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _now(offset_hours: float = 0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=offset_hours)

def _order_number(prefix: str = "") -> str:
    suffix = str(uuid.uuid4())[:6].upper()
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    tag = f"-{prefix}" if prefix else ""
    return f"ORD-{date}{tag}-{suffix}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SEED FUNCTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def seed_nodes(session: AsyncSession) -> dict[str, FulfillmentNode]:
    """Create fulfillment nodes, return {code: node}."""
    print("  → Seeding nodes...")
    nodes = {}
    for nd in NODES:
        existing = await session.scalar(select(FulfillmentNode).where(FulfillmentNode.code == nd["code"]))
        if existing:
            nodes[nd["code"]] = existing
            print(f"     skip (exists): {nd['code']}")
            continue
        node = FulfillmentNode(**nd)
        session.add(node)
        await session.flush()
        nodes[nd["code"]] = node
        print(f"     created: {nd['code']}")
    return nodes


async def seed_inventory(session: AsyncSession, nodes: dict[str, FulfillmentNode]):
    """Create inventory items and initial RECEIVED adjustments."""
    print("  → Seeding inventory...")
    sku_meta = {s["sku"]: s for s in SKUS}
    for node_code, sku_qtys in INVENTORY.items():
        node = nodes[node_code]
        for sku, qty in sku_qtys.items():
            existing = await session.scalar(
                select(InventoryItem).where(
                    InventoryItem.node_id == node.id,
                    InventoryItem.sku == sku,
                )
            )
            if existing:
                continue
            meta = sku_meta[sku]
            item = InventoryItem(
                node_id=node.id,
                sku=sku,
                product_name=meta["name"],
                quantity_on_hand=qty,
                quantity_available=qty,
                quantity_reserved=0,
                reorder_point=10,
                reorder_quantity=100,
                unit_cost=meta["unit_cost"],
                weight_lbs=meta["weight_lbs"],
                is_active=True,
            )
            session.add(item)
            await session.flush()
            adj = InventoryAdjustment(
                inventory_item_id=item.id,
                reason=InventoryAdjustmentReason.RECEIVED,
                quantity_delta=qty,
                quantity_before=0,
                quantity_after=qty,
                notes="Demo seed — initial stock",
                created_by="demo_seed",
            )
            session.add(adj)
    print(f"     created inventory for {len(INVENTORY)} nodes × {len(SKUS)} SKUs")


async def seed_sourcing_rules(session: AsyncSession):
    """Create sourcing rules."""
    print("  → Seeding sourcing rules...")
    for rule_data in SOURCING_RULES:
        existing = await session.scalar(
            select(SourcingRule).where(SourcingRule.name == rule_data["name"])
        )
        if existing:
            print(f"     skip (exists): {rule_data['name']}")
            continue
        rule = SourcingRule(**rule_data)
        session.add(rule)
        print(f"     created: {rule_data['name']}")


async def seed_orders(session: AsyncSession, nodes: dict[str, FulfillmentNode]) -> list[Order]:
    """Create 12 demo orders spanning all fulfillment types and statuses."""
    print("  → Seeding orders...")
    chi = nodes["CHI-STORE-01"]
    sfo = nodes["SFO-WH-01"]
    nyc = nodes["NYC-DC-01"]
    orders_created = []

    scenarios = [
        # (label, fulfillment_type, channel, status, customer_idx, items, node, hours_ago, is_high_value)
        ("SHIP-DELIVERED",   FulfillmentType.SHIP_TO_HOME,     OrderChannel.WEB,         OrderStatus.DELIVERED,        0, [("WGT-ALPHA-001",2,29.99), ("CBL-USB-C-030",1,9.99)],    sfo, 72,  False),
        ("SHIP-SHIPPED",     FulfillmentType.SHIP_TO_HOME,     OrderChannel.WEB,         OrderStatus.SHIPPED,          1, [("GAD-ULTRA-010",1,89.00)],                              nyc, 24,  False),
        ("SHIP-PICKING",     FulfillmentType.SHIP_TO_HOME,     OrderChannel.MOBILE,      OrderStatus.PICKING,          2, [("DOCK-HUB-050",1,59.00), ("MOUS-ERGO-080",1,49.00)],   sfo, 4,   False),
        ("SHIP-SOURCED",     FulfillmentType.SHIP_TO_HOME,     OrderChannel.WEB,         OrderStatus.SOURCED,          3, [("KBRD-MECH-070",1,129.00), ("GAD-MINI-011",2,34.50)],  nyc, 2,   True),
        ("SHIP-CONFIRMED",   FulfillmentType.SHIP_TO_HOME,     OrderChannel.API,         OrderStatus.CONFIRMED,        4, [("PWR-BANK-040",1,45.00)],                              None,0.5, False),
        ("BOPIS-READY",      FulfillmentType.STORE_PICKUP,     OrderChannel.WEB,         OrderStatus.READY_FOR_PICKUP, 0, [("SPKR-BT-060",1,79.00)],                              chi, 8,   False),
        ("BOPIS-CONFIRMED",  FulfillmentType.STORE_PICKUP,     OrderChannel.WEB,         OrderStatus.CONFIRMED,        1, [("WGT-BETA-002",2,24.99), ("CBL-HDMI-031",1,14.99)],    chi, 0.25,False),
        ("CURBSIDE-PICKING", FulfillmentType.CURBSIDE_PICKUP,  OrderChannel.MOBILE,      OrderStatus.PICKING,          2, [("GAD-MINI-011",1,34.50)],                              chi, 1,   False),
        ("SAMEDAY-SOURCED",  FulfillmentType.SAME_DAY_DELIVERY,OrderChannel.WEB,         OrderStatus.SOURCED,          3, [("WGT-ALPHA-001",3,29.99)],                             nyc, 0.5, False),
        ("MKTPLACE-SHIPPED", FulfillmentType.SHIP_TO_HOME,     OrderChannel.MARKETPLACE, OrderStatus.SHIPPED,          4, [("DOCK-HUB-050",2,59.00)],                              sfo, 48,  False),
        ("HIGH-VALUE-SOURCED",FulfillmentType.SHIP_TO_HOME,    OrderChannel.WEB,         OrderStatus.SOURCED,          0, [("KBRD-MECH-070",1,129.00), ("SPKR-BT-060",1,79.00), ("DOCK-HUB-050",1,59.00)], nyc, 1, True),
        ("BACKORDERED",      FulfillmentType.SHIP_TO_HOME,     OrderChannel.WEB,         OrderStatus.BACKORDERED,      1, [("PWR-BANK-040",20,45.00)],                             None,3,   False),
    ]

    for label, ftype, channel, status, cust_idx, items, alloc_node, hours_ago, is_high in scenarios:
        cust = CUSTOMERS[cust_idx]
        subtotal = sum(Decimal(str(price)) * qty for sku, qty, price in items)
        tax = (subtotal * Decimal("0.08")).quantize(Decimal("0.01"))
        shipping = Decimal("0.00") if ftype in (FulfillmentType.STORE_PICKUP, FulfillmentType.CURBSIDE_PICKUP) else Decimal("9.99")
        total = subtotal + tax + shipping

        order = Order(
            order_number=_order_number(label[:6]),
            channel=channel,
            fulfillment_type=ftype,
            status=status,
            payment_status=PaymentStatus.CAPTURED,
            customer_email=cust["email"],
            customer_name=cust["name"],
            subtotal=subtotal,
            tax_amount=tax,
            shipping_amount=shipping,
            discount_amount=Decimal("0.00"),
            total_amount=total,
            currency="USD",
            shipping_name=cust["name"],
            shipping_address1="123 Demo St",
            shipping_city=cust["city"],
            shipping_state=cust["state"],
            shipping_postal_code=cust["zip"],
            shipping_country="US",
            shipping_latitude=cust["lat"],
            shipping_longitude=cust["lng"],
            pickup_node_id=alloc_node.id if ftype in (FulfillmentType.STORE_PICKUP, FulfillmentType.CURBSIDE_PICKUP) and alloc_node else None,
            confirmed_at=_now(-hours_ago),
            tags=["demo", "high-value"] if is_high else ["demo"],
            metadata={"demo": True, "scenario": label, "is_high_value": is_high},
        )
        session.add(order)
        await session.flush()

        for sku, qty, price in items:
            oi = OrderItem(
                order_id=order.id,
                sku=sku,
                product_name=next(s["name"] for s in SKUS if s["sku"] == sku),
                quantity=qty,
                quantity_allocated=qty if status not in (OrderStatus.CONFIRMED, OrderStatus.BACKORDERED) else 0,
                status=OrderItemStatus.DELIVERED if status == OrderStatus.DELIVERED else OrderItemStatus.PENDING,
                unit_price=Decimal(str(price)),
                discount_amount=Decimal("0.00"),
                tax_amount=(Decimal(str(price)) * qty * Decimal("0.08")).quantize(Decimal("0.01")),
                total_price=Decimal(str(price)) * qty,
            )
            session.add(oi)
            await session.flush()

            if alloc_node and status not in (OrderStatus.CONFIRMED, OrderStatus.BACKORDERED, OrderStatus.SOURCING):
                alloc_status = AllocationStatus.DELIVERED if status == OrderStatus.DELIVERED else AllocationStatus.ALLOCATED
                alloc = FulfillmentAllocation(
                    order_id=order.id,
                    order_item_id=oi.id,
                    node_id=alloc_node.id,
                    sku=sku,
                    quantity_allocated=qty,
                    status=alloc_status,
                    allocated_at=_now(-hours_ago),
                    sourcing_score=round(random.uniform(0.65, 0.95), 3),
                    sourcing_metadata={"strategy": "DISTANCE_OPTIMAL", "demo": True},
                )
                session.add(alloc)

        orders_created.append(order)
        print(f"     created: {order.order_number} [{label}] status={status.value}")

    return orders_created


async def seed_mongodb_outcomes(mongo_db, nodes: dict[str, FulfillmentNode], orders: list[Order]):
    """Seed 150+ sourcing outcomes in MongoDB so AI Architect has real pattern data."""
    print("  → Seeding MongoDB sourcing outcomes...")

    outcomes_col = mongo_db["sourcing_outcomes"]
    events_col   = mongo_db["order_events"]

    # Clear existing demo outcomes
    await outcomes_col.delete_many({"demo": True})
    await events_col.delete_many({"demo": True})

    node_ids = {
        "CHI-STORE-01": str(nodes["CHI-STORE-01"].id),
        "SFO-WH-01":    str(nodes["SFO-WH-01"].id),
        "NYC-DC-01":    str(nodes["NYC-DC-01"].id),
    }

    clusters = [
        # (channel, region, amount_bucket, ftype, preferred_node, delivery_score, cost_score)
        ("WEB",         "IL", "50-100",  "SHIP_TO_HOME",     "CHI-STORE-01", 0.91, 0.82),
        ("WEB",         "CA", "50-100",  "SHIP_TO_HOME",     "SFO-WH-01",    0.93, 0.88),
        ("WEB",         "NY", "100-250", "SHIP_TO_HOME",     "NYC-DC-01",    0.90, 0.85),
        ("MARKETPLACE", "CA", "50-100",  "SHIP_TO_HOME",     "SFO-WH-01",    0.88, 0.90),
        ("WEB",         "IL", "0-50",    "STORE_PICKUP",     "CHI-STORE-01", 0.97, 0.95),
        ("MOBILE",      "IL", "0-50",    "CURBSIDE_PICKUP",  "CHI-STORE-01", 0.96, 0.94),
        ("WEB",         "NY", "250+",    "SHIP_TO_HOME",     "NYC-DC-01",    0.89, 0.82),
        ("WEB",         "TX", "50-100",  "SHIP_TO_HOME",     "SFO-WH-01",    0.84, 0.79),
    ]

    outcomes = []
    for i in range(180):
        cluster = clusters[i % len(clusters)]
        channel, region, amount_bucket, ftype, node_code, delivery_base, cost_base = cluster
        jitter = lambda base: min(1.0, max(0.0, base + random.uniform(-0.08, 0.08)))

        delivery_score   = jitter(delivery_base)
        cost_score       = jitter(cost_base)
        backorder_rate   = random.uniform(0.0, 0.12)
        return_rate      = random.uniform(0.0, 0.08)
        outcome_score    = (0.4 * delivery_score + 0.3 * cost_score +
                           0.2 * (1 - backorder_rate) + 0.1 * (1 - return_rate))

        created_at = _now(-random.uniform(1, 2160))  # up to 90 days ago
        outcomes.append({
            "order_id":       str(uuid.uuid4()),
            "node_id":        node_ids[node_code],
            "strategy_used":  "AI_ADAPTIVE" if i % 3 != 0 else "DISTANCE_OPTIMAL",
            "cluster_key":    f"{channel}|{region}|{amount_bucket}|{ftype}",
            "channel":        channel,
            "region":         region,
            "amount_bucket":  amount_bucket,
            "fulfillment_type": ftype,
            "delivery_score":  round(delivery_score, 3),
            "cost_score":      round(cost_score, 3),
            "backorder_rate":  round(backorder_rate, 3),
            "return_rate":     round(return_rate, 3),
            "outcome_score":   round(outcome_score, 3),
            "created_at":      created_at,
            "labeled_at":      created_at + timedelta(hours=random.uniform(24, 72)),
            "demo":            True,
        })

    await outcomes_col.insert_many(outcomes)
    print(f"     inserted {len(outcomes)} sourcing outcomes")

    # Seed order events for the created orders
    events = []
    for order in orders:
        events.append({
            "order_id":   str(order.id),
            "event_type": "order.created",
            "timestamp":  order.confirmed_at or _now(-1),
            "data":       {"order_number": order.order_number, "channel": order.channel.value, "total_amount": float(order.total_amount)},
            "demo":       True,
        })
        if order.status not in (OrderStatus.CONFIRMED,):
            events.append({
                "order_id":   str(order.id),
                "event_type": "order.sourced",
                "timestamp":  (order.confirmed_at or _now(-1)) + timedelta(minutes=random.randint(1, 5)),
                "data":       {"strategy": "AI_ADAPTIVE", "node": "demo-node", "score": round(random.uniform(0.7, 0.95), 3)},
                "demo":       True,
            })

    if events:
        await events_col.insert_many(events)
        print(f"     inserted {len(events)} order events")

    # Seed node performance metrics
    perf_col = mongo_db["node_performance_metrics"]
    await perf_col.delete_many({"demo": True})
    perf_docs = []
    for node_code, node in nodes.items():
        cap = {"CHI-STORE-01": 120, "SFO-WH-01": 800, "NYC-DC-01": 1000}[node_code]
        curr = {"CHI-STORE-01": 108, "SFO-WH-01": 312, "NYC-DC-01": 420}[node_code]
        perf_docs.append({
            "node_id":              str(node.id),
            "node_code":            node_code,
            "avg_delivery_score":   round(random.uniform(0.82, 0.94), 3),
            "avg_cost_score":       round(random.uniform(0.78, 0.92), 3),
            "avg_outcome_score":    round(random.uniform(0.80, 0.93), 3),
            "total_orders":         random.randint(800, 3500),
            "capacity_utilization": round(curr / cap, 2),
            "computed_at":          _now(),
            "demo":                 True,
        })
    await perf_col.insert_many(perf_docs)
    print(f"     inserted {len(perf_docs)} node performance records")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def seed_db(db_url: str, mongo_db):
    """Seed a single PostgreSQL database."""
    engine = create_async_engine(db_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            async with session.begin():
                nodes  = await seed_nodes(session)
                await seed_inventory(session, nodes)
                await seed_sourcing_rules(session)
                orders = await seed_orders(session, nodes)
        await seed_mongodb_outcomes(mongo_db, nodes, orders)
    finally:
        await engine.dispose()


async def main():
    print("\n🚀 KubeRiva Demo Seed — starting\n")

    # MongoDB
    mongo_client = AsyncIOMotorClient(settings.MONGODB_URL)
    mongo_db     = mongo_client[settings.MONGODB_DB]

    # Seed only the production database (settings.DATABASE_URL)
    await seed_db(settings.DATABASE_URL, mongo_db)

    mongo_client.close()

    print("\n✅ Demo seed complete!\n")
    print("What's been created:")
    print("  • 3 fulfillment nodes (Chicago near capacity, SF Warehouse, NYC DC)")
    print("  • 12 SKUs × 3 nodes = 36 inventory items")
    print("  • 5 sourcing rules (including AI_ADAPTIVE for Web channel)")
    print("  • 12 orders spanning all fulfillment types and statuses")
    print("  • 180 sourcing outcomes in MongoDB (AI Architect pattern data)")
    print("  • Node performance metrics in MongoDB")
    print("\nDemo-ready order statuses:")
    print("  • CONFIRMED  — ready to trigger sourcing live during demo")
    print("  • SOURCED    — allocation visible, high-value order at NYC DC")
    print("  • PICKING    — lifecycle in progress")
    print("  • SHIPPED    — tracking visible")
    print("  • DELIVERED  — full audit trail")
    print("  • READY_FOR_PICKUP — BOPIS order at Chicago store")
    print("  • BACKORDERED — shows AI fallback behavior")
    print("\nStress test: Chicago node is at 108/120 capacity (90% full)")
    print("Run more orders through WEB channel to hit the cap during demo.\n")


if __name__ == "__main__":
    asyncio.run(main())
