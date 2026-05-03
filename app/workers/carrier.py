"""Carrier worker — mock carrier integration for label creation and tracking."""
import logging
import uuid
import random
from datetime import datetime, timedelta

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

CARRIERS = ["UPS", "FedEx", "USPS", "DHL", "OnTrac"]
SERVICE_LEVELS = ["Ground", "2-Day", "Overnight", "Priority Mail"]


def _get_sync_session(environment_id: str = ""):
    import re
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.workers.env_utils import get_env_db_url
    sync_url = re.sub(r"\+asyncpg", "", get_env_db_url(environment_id))
    engine = create_engine(sync_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def _log_event_sync(order_id: str, event_type: str, data: dict, environment_id: str = ""):
    """Write an audit event to MongoDB from a synchronous Celery context."""
    import asyncio
    from app.config import settings
    from app.workers.env_utils import get_env_mongo_events_db

    mongo_events_db = get_env_mongo_events_db(environment_id)

    async def _do():
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000, uuidRepresentation="standard")
        try:
            await client[mongo_events_db].order_events.insert_one({
                "order_id": order_id,
                "event_type": event_type,
                "timestamp": datetime.utcnow(),
                "data": data,
            })
        finally:
            client.close()

    try:
        asyncio.run(_do())
    except Exception as exc:
        logger.warning(f"Failed to log event {event_type} for order {order_id}: {exc}")


def _update_sourcing_outcomes_shipped(order_id: str, allocations, shipments_created, environment_id: str = ""):
    """After SHIPPED: write actual_cost and cost_variance_pct to sourcing_outcomes docs."""
    import asyncio
    from app.config import settings
    from app.workers.env_utils import get_env_mongo_ai_db

    mongo_ai_db = get_env_mongo_ai_db(environment_id)

    # Build a map of node_id → actual shipping cost from the created shipments
    node_cost: dict = {}
    for shipment, carrier, tracking, est_delivery, items, node_id in shipments_created:
        if node_id:
            node_cost[str(node_id)] = shipment.shipping_cost or 0.0

    async def _do():
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000, uuidRepresentation="standard")
        try:
            db = client[mongo_ai_db]
            for alloc in allocations:
                actual_cost = node_cost.get(str(alloc.node_id)) if alloc.node_id else None
                if actual_cost is None:
                    continue
                # Compute cost_variance_pct relative to predicted_cost if available
                update_fields: dict = {"actual_cost": actual_cost}
                doc = await db.sourcing_outcomes.find_one(
                    {"order_id": str(order_id), "allocation_id": str(alloc.id)},
                    {"predicted_cost": 1},
                )
                if doc and doc.get("predicted_cost"):
                    predicted = doc["predicted_cost"]
                    if predicted > 0:
                        variance_pct = round((actual_cost - predicted) / predicted * 100, 2)
                        update_fields["cost_variance_pct"] = variance_pct
                await db.sourcing_outcomes.update_one(
                    {"order_id": str(order_id), "allocation_id": str(alloc.id)},
                    {"$set": update_fields},
                )
        finally:
            client.close()

    try:
        asyncio.run(_do())
    except Exception as exc:
        logger.warning(f"Failed to update sourcing_outcomes (shipped) for order {order_id}: {exc}")


def _update_sourcing_outcomes_delivered(order_id: str, alloc_ids: set, delivered_at: datetime, environment_id: str = ""):
    """After DELIVERED: write actual_delivery_hours to sourcing_outcomes docs."""
    import asyncio
    from app.config import settings
    from app.workers.env_utils import get_env_mongo_ai_db

    mongo_ai_db = get_env_mongo_ai_db(environment_id)

    async def _do():
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000, uuidRepresentation="standard")
        try:
            db = client[mongo_ai_db]
            for alloc_id in alloc_ids:
                doc = await db.sourcing_outcomes.find_one(
                    {"order_id": str(order_id), "allocation_id": alloc_id},
                    {"sourced_at": 1},
                )
                if not doc:
                    continue
                sourced_at_raw = doc.get("sourced_at")
                if sourced_at_raw:
                    try:
                        if isinstance(sourced_at_raw, str):
                            from datetime import timezone
                            sourced_dt = datetime.fromisoformat(sourced_at_raw.replace("Z", "+00:00"))
                            if sourced_dt.tzinfo:
                                delivered_utc = delivered_at.replace(tzinfo=timezone.utc)
                                delivery_hours = round(
                                    (delivered_utc - sourced_dt).total_seconds() / 3600, 2
                                )
                            else:
                                delivery_hours = round(
                                    (delivered_at - sourced_dt.replace(tzinfo=None)).total_seconds() / 3600, 2
                                )
                        else:
                            delivery_hours = round(
                                (delivered_at - sourced_at_raw).total_seconds() / 3600, 2
                            )
                        await db.sourcing_outcomes.update_one(
                            {"_id": doc["_id"]},
                            {"$set": {"actual_delivery_hours": delivery_hours}},
                        )
                    except Exception:
                        pass
        finally:
            client.close()

    try:
        asyncio.run(_do())
    except Exception as exc:
        logger.warning(f"Failed to update sourcing_outcomes (delivered) for order {order_id}: {exc}")


def _mock_tracking_number(carrier: str) -> str:
    """Generate a realistic-looking mock tracking number."""
    prefix = {"UPS": "1Z", "FedEx": "7489", "USPS": "9400", "DHL": "JD", "OnTrac": "C"}.get(carrier, "TRK")
    return f"{prefix}{uuid.uuid4().hex[:14].upper()}"


@celery_app.task(
    name="app.workers.carrier.book_shipment",
    queue="carrier",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
    reject_on_worker_lost=True,
)
def book_shipment(self, order_id: str, environment_id: str = ""):
    """Book carrier, create label, and transition to SHIPPED."""
    from app.models.postgres.order_models import Order, Shipment, FulfillmentAllocation, OrderStatus, AllocationStatus, ShipmentStatus
    from app.models.postgres.inventory_models import InventoryItem
    # Ensure all FK-referenced tables are in mapper metadata
    from app.models.postgres import connector_models, auth_models, node_models  # noqa

    session, engine = _get_sync_session(environment_id)
    try:
        order = session.query(Order).filter(Order.id == order_id).first()
        if not order:
            return

        # Never book a carrier for pickup fulfillment types — they have no shipment
        from app.services.lifecycle_engine import resolve_lifecycle_sync, should_book_carrier, PICKUP_TYPES
        ft = order.fulfillment_type.value if hasattr(order.fulfillment_type, "value") else str(order.fulfillment_type or "")
        ch = order.channel.value if hasattr(order.channel, "value") else str(order.channel or "")
        if ft in PICKUP_TYPES:
            logger.info(f"Order {order_id} is {ft} — skipping carrier booking")
            return
        lc_dict, _ = resolve_lifecycle_sync(environment_id, ft, ch)
        if not should_book_carrier(lc_dict, ft):
            logger.info(f"Order {order_id} lifecycle '{lc_dict['name'] if lc_dict else 'none'}' does not include carrier booking — skipping")
            return

        # Allow orders in READY_TO_SHIP, PACKING, PARTIALLY_DELIVERED, or BACKORDERED with new allocations
        if order.status not in (OrderStatus.READY_TO_SHIP, OrderStatus.PACKING, OrderStatus.PARTIALLY_DELIVERED, OrderStatus.BACKORDERED):
            return

        # For PARTIALLY_DELIVERED or BACKORDERED orders, only process PACKED allocations without shipments
        if order.status in (OrderStatus.PARTIALLY_DELIVERED, OrderStatus.BACKORDERED):
            allocations = session.query(FulfillmentAllocation).outerjoin(
                Shipment, Shipment.allocation_id == FulfillmentAllocation.id
            ).filter(
                FulfillmentAllocation.order_id == order_id,
                FulfillmentAllocation.status == AllocationStatus.PACKED,
                Shipment.id.is_(None),  # No shipment exists for this allocation
            ).all()
        else:
            # Only process allocations that have not yet been shipped or delivered.
            # This prevents duplicate shipments when an order is re-sourced after
            # a partial delivery and the pipeline runs a second time.
            allocations = session.query(FulfillmentAllocation).filter(
                FulfillmentAllocation.order_id == order_id,
                FulfillmentAllocation.status.notin_([
                    AllocationStatus.SHIPPED,
                    AllocationStatus.DELIVERED,
                    AllocationStatus.CANCELLED,
                ]),
            ).all()
        
        if not allocations:
            return

        shipments_created = []
        allocations_by_node = {}
        for alloc in allocations:
            allocations_by_node.setdefault(alloc.node_id, []).append(alloc)

        for node_id, node_allocations in allocations_by_node.items():
            carrier = random.choice(CARRIERS)
            service = random.choice(SERVICE_LEVELS)
            tracking = _mock_tracking_number(carrier)
            shipping_cost = round(random.uniform(4.99, 24.99), 2)
            estimated_days = {"Ground": 5, "2-Day": 2, "Overnight": 1, "Priority Mail": 3}.get(service, 3)
            est_delivery = datetime.utcnow() + timedelta(days=estimated_days)

            shipped_items = [
                {
                    "allocation_id": str(a.id),
                    "sku": a.sku,
                    "quantity": a.quantity_allocated,
                    "node_id": str(a.node_id) if a.node_id else None,
                }
                for a in node_allocations
            ]

            shipment = Shipment(
                order_id=order.id,
                allocation_id=node_allocations[0].id,
                tracking_number=tracking,
                carrier=carrier,
                service_level=service,
                status=ShipmentStatus.LABEL_CREATED,
                label_url=f"https://labels.example.com/{tracking}.pdf",
                label_created_at=datetime.utcnow(),
                shipped_at=datetime.utcnow(),
                estimated_delivery_at=est_delivery,
                shipping_cost=shipping_cost,
                tracking_events=[
                    {
                        "timestamp": datetime.utcnow().isoformat(),
                        "status": "LABEL_CREATED",
                        "location": "Origin Facility",
                        "description": "Shipping label created",
                        "items": shipped_items,
                    }
                ],
            )
            session.add(shipment)
            shipments_created.append((shipment, carrier, tracking, est_delivery, shipped_items, node_id))

            for alloc in node_allocations:
                alloc.status = AllocationStatus.SHIPPED
                alloc.shipped_at = datetime.utcnow()

            # ── Inventory deduction on shipment ─────────────────────────────
            # Goods physically leave the warehouse: reduce on_hand and release
            # the reservation that was placed at sourcing time.
            for alloc in node_allocations:
                if not alloc.node_id or not alloc.sku:
                    continue
                inv = session.query(InventoryItem).filter(
                    InventoryItem.node_id == alloc.node_id,
                    InventoryItem.sku == alloc.sku,
                ).first()
                if inv:
                    qty = alloc.quantity_allocated or 0
                    inv.quantity_on_hand    = max(0, inv.quantity_on_hand    - qty)
                    inv.quantity_reserved   = max(0, inv.quantity_reserved   - qty)
                    inv.quantity_available  = max(0, inv.quantity_on_hand    - inv.quantity_reserved)

        order.status = OrderStatus.SHIPPED

        # Update order line statuses based on ALL allocations and shipments (not just the ones created in this call)
        from app.services.status_rollup import compute_order_line_status_from_shipments
        from app.models.postgres.order_models import OrderItem
        
        # Fetch ALL allocations and shipments for this order to get accurate rollup
        all_allocations = session.query(FulfillmentAllocation).filter(
            FulfillmentAllocation.order_id == order_id
        ).all()
        
        all_shipments = session.query(Shipment).filter(
            Shipment.order_id == order_id
        ).all()
        
        order_lines = session.query(OrderItem).filter(OrderItem.order_id == order.id).all()
        
        for line in order_lines:
            breakdown = compute_order_line_status_from_shipments(
                order_line_id=str(line.id),
                order_line_sku=line.sku,
                order_line_quantity=line.quantity,
                allocations=all_allocations,  # FIXED: Pass ALL allocations, not just new ones
                shipments=all_shipments,      # FIXED: Pass ALL shipments, not just new ones
            )
            line.status = breakdown.status
            line.quantity_allocated = breakdown.quantity_allocated
            line.quantity_backordered = breakdown.quantity_backordered
            line.quantity_shipped = breakdown.quantity_shipped
            line.quantity_delivered = breakdown.quantity_delivered

        # Increment daily order counter once per unique node participating in split
        from app.models.postgres.node_models import FulfillmentNode
        unique_node_ids = {alloc.node_id for alloc in allocations if alloc.node_id is not None}
        for node_id in unique_node_ids:
            node = session.query(FulfillmentNode).filter(FulfillmentNode.id == node_id).first()
            if node:
                node.current_daily_orders += 1

        session.commit()
        logger.info(f"Order {order_id} SHIPPED with {len(shipments_created)} shipment(s)")

        # Update sourcing_outcomes with actual_cost for cost_variance_pct computation
        _update_sourcing_outcomes_shipped(order_id, allocations, shipments_created, environment_id)

        _log_event_sync(order_id, "order.shipped", {
            "new_status": "SHIPPED",
            "old_status": "READY_TO_SHIP",
            "shipment_count": len(shipments_created),
            "trackings": [s[2] for s in shipments_created],
            "shipments": [
                {
                    "tracking_number": s[2],
                    "carrier": s[1],
                    "node_id": str(s[5]) if s[5] else None,
                    "items": s[4],
                }
                for s in shipments_created
            ],
        }, environment_id)

        # Notify customer
        for _, carrier, tracking, est_delivery, _, _ in shipments_created:
            celery_app.send_task(
                "app.workers.notifications.send_shipment_notification",
                args=[order_id, tracking, carrier, est_delivery.isoformat()],
                queue="notifications",
            )

        # Webhook
        celery_app.send_task(
            "app.workers.webhooks.dispatch_webhook",
            args=[order_id, "order.shipped"],
            queue="webhooks",
        )

        # Push fulfillment to external connector (Shopify, Amazon, etc.)
        if order.connector_id:
            celery_app.send_task(
                "app.workers.connectors.sync_fulfillment",
                args=[order_id],
                queue="connectors",
            )

        # Schedule delivery simulation for each shipment
        for shipment, _, _, _, _, _ in shipments_created:
            celery_app.send_task(
                "app.workers.carrier.simulate_delivery",
                args=[order_id, str(shipment.id), environment_id],
                queue="carrier",
                countdown=10,
            )

    except Exception as exc:
        session.rollback()
        logger.exception(f"book_shipment failed for {order_id}: {exc}")
        from app.services.monitoring import capture_error_sync, SOURCE_CARRIER
        capture_error_sync(exc, SOURCE_CARRIER,
            task_context={"task": "book_shipment", "queue": "carrier", "retry": self.request.retries},
            order_context={"order_id": order_id})
        raise self.retry(exc=exc)
    finally:
        session.close()
        engine.dispose()


@celery_app.task(
    name="app.workers.carrier.simulate_delivery",
    queue="carrier",
)
def simulate_delivery(order_id: str, shipment_id: str, environment_id: str = ""):
    """Simulate package delivery (for demo/testing)."""
    from app.models.postgres.order_models import Order, Shipment, OrderStatus, ShipmentStatus

    session, engine = _get_sync_session(environment_id)
    try:
        # Lock the order row first to serialize concurrent simulate_delivery tasks
        # for the same order — prevents race conditions on order_items rollup.
        order = session.query(Order).filter(Order.id == order_id).with_for_update().first()
        shipment = session.query(Shipment).filter(Shipment.id == shipment_id).first()
        if not shipment or not order:
            return

        now = datetime.utcnow()
        events = list(shipment.tracking_events or [])
        events.append({
            "timestamp": now.isoformat(),
            "status": "IN_TRANSIT",
            "location": "Regional Sort Facility",
            "description": "Package in transit",
        })
        events.append({
            "timestamp": now.isoformat(),
            "status": "OUT_FOR_DELIVERY",
            "location": "Local Delivery Facility",
            "description": "Out for delivery",
        })
        events.append({
            "timestamp": now.isoformat(),
            "status": "DELIVERED",
            "location": "Customer Address",
            "description": "Package delivered",
        })

        shipment.tracking_events = events
        shipment.status = ShipmentStatus.DELIVERED
        shipment.actual_delivery_at = now

        # Sync ALL allocations covered by this shipment to DELIVERED.
        # For grouped shipments (one shipment per node, multiple SKUs) the
        # sibling allocation IDs are stored in tracking_events[0]["items"];
        # only the first allocation is stored in shipment.allocation_id.
        from app.models.postgres.order_models import OrderItem, FulfillmentAllocation, AllocationStatus
        alloc_ids_in_shipment = set()
        if shipment.allocation_id:
            alloc_ids_in_shipment.add(str(shipment.allocation_id))
        for event in (shipment.tracking_events or []):
            for item in event.get('items', []):
                aid = item.get('allocation_id')
                if aid:
                    alloc_ids_in_shipment.add(str(aid))
        for alloc_id in alloc_ids_in_shipment:
            alloc = session.query(FulfillmentAllocation).filter(
                FulfillmentAllocation.id == alloc_id
            ).first()
            if alloc and alloc.status != AllocationStatus.DELIVERED:
                alloc.status = AllocationStatus.DELIVERED

        # Recompute order line and order statuses from shipment data
        from app.services.status_rollup import compute_order_line_status_from_shipments, compute_order_status_from_lines

        all_allocations = session.query(FulfillmentAllocation).filter(
            FulfillmentAllocation.order_id == order.id
        ).all()
        all_shipments = session.query(Shipment).filter(
            Shipment.order_id == order.id
        ).all()

        order_lines = session.query(OrderItem).filter(OrderItem.order_id == order.id).all()
        
        # Update each order line status based on shipment statuses
        for line in order_lines:
            breakdown = compute_order_line_status_from_shipments(
                order_line_id=str(line.id),
                order_line_sku=line.sku,
                order_line_quantity=line.quantity,
                allocations=all_allocations,
                shipments=all_shipments,
            )
            line.status = breakdown.status
            line.quantity_allocated = breakdown.quantity_allocated
            line.quantity_shipped = breakdown.quantity_shipped
            line.quantity_delivered = breakdown.quantity_delivered
            line.quantity_backordered = breakdown.quantity_backordered
        
        # Roll up order status from order lines
        new_order_status = compute_order_status_from_lines(order_lines)
        if new_order_status:
            old_status = order.status.value if hasattr(order.status, 'value') else str(order.status)
            order.status = new_order_status
            if new_order_status == OrderStatus.DELIVERED.value:
                order.delivered_at = now
        
        session.commit()
        logger.info(f"Order {order_id} status updated to {order.status}")

        # Update sourcing_outcomes with actual_delivery_hours for learning pipeline
        if order.status in (OrderStatus.DELIVERED, OrderStatus.PARTIALLY_DELIVERED):
            _update_sourcing_outcomes_delivered(str(order_id), alloc_ids_in_shipment, now, environment_id)

        _log_event_sync(order_id, f"order.{order.status.value.lower() if hasattr(order.status, 'value') else str(order.status).lower()}", {
            "new_status": order.status.value if hasattr(order.status, 'value') else str(order.status),
            "old_status": old_status,
            "carrier": shipment.carrier,
            "tracking_number": shipment.tracking_number,
            "delivered_at": now.isoformat() if order.status in (OrderStatus.DELIVERED, OrderStatus.PARTIALLY_DELIVERED) else None,
        }, environment_id)

        celery_app.send_task(
            "app.workers.webhooks.dispatch_webhook",
            args=[order_id, f"order.{order.status.value.lower() if hasattr(order.status, 'value') else str(order.status).lower()}"],
            queue="webhooks",
        )
        
        if order.status in (OrderStatus.DELIVERED, OrderStatus.PARTIALLY_DELIVERED):
            celery_app.send_task(
                "app.workers.notifications.send_delivery_notification",
                args=[order_id],
                queue="notifications",
            )
    finally:
        session.close()
        engine.dispose()


@celery_app.task(
    name="app.workers.carrier.sync_all_tracking",
    queue="carrier",
)
def sync_all_tracking():
    """Periodic task: sync tracking for in-transit shipments."""
    from app.models.postgres.order_models import Shipment, ShipmentStatus

    session, engine = _get_sync_session()
    try:
        in_transit = session.query(Shipment).filter(
            Shipment.status.in_([ShipmentStatus.PICKED_UP, ShipmentStatus.IN_TRANSIT])
        ).limit(100).all()
        logger.info(f"Syncing tracking for {len(in_transit)} shipments")
        # In production, call carrier APIs here
    finally:
        session.close()
        engine.dispose()

@celery_app.task(
    name="app.workers.carrier.process_packed_allocations_without_shipments",
    queue="carrier",
)
def process_packed_allocations_without_shipments():
    """Periodic task: create shipments for PACKED allocations without shipments.
    
    Handles the case where allocations are created dynamically (e.g., via backorder re-sourcing)
    but the order is already PARTIALLY_DELIVERED, so the normal book_shipment task doesn't trigger.
    """
    from app.models.postgres.order_models import Order, Shipment, FulfillmentAllocation, AllocationStatus

    session, engine = _get_sync_session()
    try:
        # Find orders with PACKED allocations that lack shipments
        orders_to_process = session.query(Order.id).distinct().filter(
            Order.id.in_(
                session.query(FulfillmentAllocation.order_id).outerjoin(
                    Shipment, Shipment.allocation_id == FulfillmentAllocation.id
                ).filter(
                    FulfillmentAllocation.status == AllocationStatus.PACKED,
                    Shipment.id.is_(None),
                ).distinct()
            )
        ).all()
        
        processed_count = 0
        for (order_id,) in orders_to_process:
            # Trigger book_shipment for each order
            celery_app.send_task(
                "app.workers.carrier.book_shipment",
                args=[order_id],
                queue="carrier",
            )
            processed_count += 1
        
        if processed_count > 0:
            logger.info(f"Queued book_shipment for {processed_count} orders with unpacked allocations")
        else:
            logger.debug("No orders with unpacked allocations found")
    
    except Exception as exc:
        logger.exception(f"process_packed_allocations_without_shipments failed: {exc}")
    finally:
        session.close()
        engine.dispose()