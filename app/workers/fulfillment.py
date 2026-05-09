"""Fulfillment worker — Pick → Pack → ReadyToShip pipeline."""
import logging
from datetime import datetime
from celery import shared_task

from app.config import settings
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_sync_session(environment_id: str = ""):
    """Create a synchronous SQLAlchemy session for Celery tasks."""
    import re
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.workers.env_utils import get_env_db_url
    sync_url = re.sub(r"\+asyncpg", "", get_env_db_url(environment_id))
    engine = create_engine(sync_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def _log_event_sync(order_id: str, event_type: str, data: dict, environment_id: str = ""):
    """Write an audit event to MongoDB from a synchronous Celery context.
    Creates its own Motor client per call to avoid event-loop conflicts."""
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


@celery_app.task(
    name="app.workers.fulfillment.start_picking",
    queue="fulfillment",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
    reject_on_worker_lost=True,
)
def start_picking(self, order_id: str, environment_id: str = ""):
    """Transition order and allocations to PICKING status.

    CRITICAL: Validates order state and allocation consistency before transition.
    """
    from app.models.postgres import (  # noqa: register all mappers Order references
        order_models, inventory_models, node_models, sourcing_rule_models,
        connector_models, auth_models, lifecycle_models, b2b_models, brand_models,
    )
    from app.models.postgres.order_models import Order, FulfillmentAllocation, OrderStatus, AllocationStatus

    # Idempotency guard — prevent duplicate picking transitions from concurrent
    # task deliveries (e.g. Celery retry racing with the original message).
    import redis as redis_lib
    _r = redis_lib.from_url(settings.REDIS_URL)
    _env_ns = environment_id or "default"
    idem_key = f"task:start_picking:{_env_ns}:{order_id}"
    if not _r.set(idem_key, "1", nx=True, ex=600):
        logger.info(f"start_picking duplicate detected for {order_id}, skipping")
        return

    session, engine = _get_sync_session(environment_id)
    try:
        order = session.query(Order).filter(Order.id == order_id).first()
        if not order:
            logger.error(f"Order {order_id} not found")
            return

        # VALIDATION: Check order is in valid state for picking
        # Allow both SOURCED (fully allocated) and BACKORDERED (partially allocated)
        if order.status not in (OrderStatus.SOURCED, OrderStatus.BACKORDERED):
            logger.error(f"Order {order_id} cannot transition to PICKING from {order.status}; "
                        f"expected SOURCED or BACKORDERED")
            return

        # VALIDATION: Load and validate allocations exist
        allocations = session.query(FulfillmentAllocation).filter(
            FulfillmentAllocation.order_id == order_id,
            FulfillmentAllocation.status == AllocationStatus.ALLOCATED,
        ).all()

        if not allocations:
            logger.error(f"Order {order_id} has no ALLOCATED allocations; cannot start picking")
            return

        # VALIDATION: Verify all allocations have valid quantities
        for alloc in allocations:
            if alloc.quantity_allocated <= 0:
                logger.error(f"Allocation {alloc.id} has invalid quantity {alloc.quantity_allocated}")
                return
            if not alloc.order_item_id:
                logger.warning(f"Allocation {alloc.id} has no order_item_id; continuing anyway")

        # VALIDATION: Verify order items are fully allocated
        order_items = [item for item in order.line_items]
        if not order_items:
            logger.error(f"Order {order_id} has no line items")
            return

        total_allocated = 0
        for alloc in allocations:
            total_allocated += alloc.quantity_allocated
        
        total_needed = sum(item.quantity for item in order_items)
        if total_allocated < total_needed:
            logger.warning(f"Order {order_id} is partially allocated ({total_allocated}/{total_needed}); "
                          f"proceeding with picking anyway")

        # All validations passed - proceed with transition
        order.status = OrderStatus.PICKING
        for alloc in allocations:
            alloc.status = AllocationStatus.PICKING
            alloc.picking_started_at = datetime.utcnow()

        session.commit()
        logger.info(f"Order {order_id} → PICKING ({len(allocations)} allocations verified)")

        # Log audit event
        _log_event_sync(order_id, "order.picking", {
            "new_status": "PICKING",
            "old_status": "SOURCED",
            "allocations_count": len(allocations),
            "allocation_ids": [str(a.id) for a in allocations],
            "validation": "passed",
        }, environment_id)

        # Auto-advance to packing. In production this would be triggered by
        # a warehouse scan event; for non-production environments we auto-advance
        # after a short delay to keep the demo pipeline moving.
        from app.config import settings
        pick_delay = 5 if settings.ENVIRONMENT != "production" else 300
        celery_app.send_task(
            "app.workers.fulfillment.complete_packing",
            args=[order_id, environment_id],
            queue="fulfillment",
            countdown=pick_delay,
        )
    except Exception as exc:
        session.rollback()
        logger.exception(f"Picking failed for {order_id}: {exc}")
        from app.services.monitoring import capture_error_sync, SOURCE_FULFILLMENT
        capture_error_sync(exc, SOURCE_FULFILLMENT,
            task_context={"task": "start_picking", "queue": "fulfillment", "retry": self.request.retries},
            order_context={"order_id": order_id})
        raise self.retry(exc=exc)
    finally:
        session.close()
        engine.dispose()


@celery_app.task(
    name="app.workers.fulfillment.complete_packing",
    queue="fulfillment",
    bind=True,
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def complete_packing(self, order_id: str, environment_id: str = ""):
    """Transition order PACKING → READY_TO_SHIP or READY_FOR_PICKUP per lifecycle."""
    from app.models.postgres import (  # noqa: register all mappers Order references
        order_models, inventory_models, node_models, sourcing_rule_models,
        connector_models, auth_models, lifecycle_models, b2b_models, brand_models,
    )
    from app.models.postgres.order_models import Order, FulfillmentAllocation, OrderStatus, AllocationStatus
    from app.services.lifecycle_engine import (
        resolve_lifecycle_sync, get_post_packing_status, get_action_for_status,
        should_book_carrier, ACTION_BOOK_SHIPMENT, ACTION_SEND_PICKUP_READY,
    )

    session, engine = _get_sync_session(environment_id)
    try:
        order = session.query(Order).filter(Order.id == order_id).first()
        if not order or order.status != OrderStatus.PICKING:
            return

        ft = order.fulfillment_type.value if hasattr(order.fulfillment_type, "value") else str(order.fulfillment_type or "")
        ch = order.channel.value if hasattr(order.channel, "value") else str(order.channel or "")
        ot = None
        if hasattr(order, "order_type") and order.order_type is not None:
            ot = order.order_type.value if hasattr(order.order_type, "value") else str(order.order_type)
        bid = str(order.brand_id) if hasattr(order, "brand_id") and order.brand_id else None

        lc_dict, _ = resolve_lifecycle_sync(environment_id, ft, ch, pipeline_type="ORDER", order_type=ot, brand_id=bid)
        post_packing = get_post_packing_status(lc_dict, ft)

        order.status = OrderStatus.PACKING
        allocations = session.query(FulfillmentAllocation).filter(
            FulfillmentAllocation.order_id == order_id,
            FulfillmentAllocation.status == AllocationStatus.PICKING,
        ).all()

        for alloc in allocations:
            alloc.status = AllocationStatus.PACKED
            alloc.packed_at = datetime.utcnow()

        session.commit()
        logger.info(f"Order {order_id} → PACKING")

        _log_event_sync(order_id, "order.packing", {
            "new_status": "PACKING",
            "old_status": "PICKING",
            "allocations_packed": len(allocations),
        }, environment_id)

        # Transition to the lifecycle-determined next status
        try:
            order.status = OrderStatus(post_packing)
        except ValueError:
            order.status = OrderStatus.READY_TO_SHIP
            post_packing = "READY_TO_SHIP"

        if post_packing == "READY_FOR_PICKUP":
            order.pickup_ready_at = datetime.utcnow()

        session.commit()
        logger.info(f"Order {order_id} → {post_packing} (lifecycle: {lc_dict['name'] if lc_dict else 'default'})")

        _log_event_sync(order_id, f"order.{post_packing.lower()}", {
            "new_status": post_packing,
            "old_status": "PACKING",
            "lifecycle": lc_dict["name"] if lc_dict else "default",
        }, environment_id)

        # Fire the action configured for this status
        action = get_action_for_status(lc_dict, post_packing, ft)

        if action == ACTION_BOOK_SHIPMENT:
            celery_app.send_task(
                "app.workers.carrier.book_shipment",
                args=[order_id, environment_id],
                queue="carrier",
                countdown=2,
            )
        elif action == ACTION_SEND_PICKUP_READY:
            celery_app.send_task(
                "app.workers.notifications.send_pickup_ready_notification",
                args=[order_id],
                queue="notifications",
            )
        elif should_book_carrier(lc_dict, ft):
            # Fallback: if no explicit action but type is a shipping type, still book carrier
            celery_app.send_task(
                "app.workers.carrier.book_shipment",
                args=[order_id, environment_id],
                queue="carrier",
                countdown=2,
            )

        # Generic packing notification (only for shipping types)
        if post_packing == "READY_TO_SHIP":
            celery_app.send_task(
                "app.workers.notifications.send_packing_notification",
                args=[order_id],
                queue="notifications",
            )

    except Exception as exc:
        session.rollback()
        logger.exception(f"Packing failed for {order_id}: {exc}")
        from app.services.monitoring import capture_error_sync, SOURCE_FULFILLMENT
        capture_error_sync(exc, SOURCE_FULFILLMENT,
            task_context={"task": "complete_packing", "queue": "fulfillment", "retry": self.request.retries},
            order_context={"order_id": order_id})
        raise self.retry(exc=exc)
    finally:
        session.close()
        engine.dispose()


@celery_app.task(
    name="app.workers.fulfillment.reset_node_daily_counters",
    queue="fulfillment",
)
def reset_node_daily_counters():
    """Reset current_daily_orders for all nodes at midnight."""
    from app.models.postgres.node_models import FulfillmentNode

    session, engine = _get_sync_session()
    try:
        session.query(FulfillmentNode).update({"current_daily_orders": 0})
        session.commit()
        logger.info("Node daily order counters reset")
    except Exception as exc:
        session.rollback()
        logger.exception(f"Failed to reset counters: {exc}")
    finally:
        session.close()
        engine.dispose()
