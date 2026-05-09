"""Sourcing worker — triggers the sourcing engine for new orders."""
import logging
from datetime import datetime, timedelta
from celery import shared_task

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.workers.sourcing.source_order",
    queue="sourcing",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
    reject_on_worker_lost=True,
    rate_limit="100/m",
)
def source_order(self, order_id: str, environment_id: str = ""):
    """Run sourcing engine for an order and transition it through the pipeline."""
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy.orm import selectinload
    from sqlalchemy import select
    from app.config import settings
    from app.models.postgres.order_models import Order, OrderStatus
    # Import all related mappers so SQLAlchemy can resolve cross-model relationships
    import app.models.postgres.brand_models      # noqa: F401 — Brand (order.brand_id, order.seller_brand_id)
    import app.models.postgres.b2b_models        # noqa: F401 — CustomerAccount
    import app.models.postgres.auth_models       # noqa: F401 — User (order.approved_by_id)
    import app.models.postgres.node_models       # noqa: F401 — FulfillmentNode
    import app.models.postgres.connector_models  # noqa: F401 — Connector
    import app.models.postgres.sourcing_rule_models  # noqa: F401 — SourcingRule
    from app.services.sourcing_engine import SourcingEngine
    from app.workers.env_utils import get_env_db_url, get_env_mongo_events_db, get_env_mongo_ai_db

    db_url = get_env_db_url(environment_id)
    mongo_events_db = get_env_mongo_events_db(environment_id)
    mongo_ai_db = get_env_mongo_ai_db(environment_id)

    async def _run():
        # Import ALL model modules so SQLAlchemy mapper metadata includes every
        # table referenced by FKs (e.g. orders.connector_id → connectors).
        from app.models.postgres import (  # noqa
            order_models, inventory_models, node_models,
            sourcing_rule_models, connector_models, auth_models, lifecycle_models,
            b2b_models, brand_models,
        )
        engine = create_async_engine(db_url, echo=False)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            result = await session.execute(
                select(Order)
                .options(selectinload(Order.line_items))
                .where(Order.id == order_id)
            )
            order = result.scalar_one_or_none()
            if not order:
                logger.error(f"Order {order_id} not found for sourcing")
                return

            # CRITICAL: Only allow sourcing for orders that haven't entered fulfillment yet
            # or have been explicitly returned to BACKORDERED for re-allocation
            if order.status not in (
                OrderStatus.CONFIRMED,
                OrderStatus.BACKORDERED,
                OrderStatus.PARTIALLY_DELIVERED,  # Allow re-allocation of remaining items only
            ):
                logger.info(
                    f"Order {order_id} cannot be sourced (status={order.status}); "
                    f"only PENDING, CONFIRMED, BACKORDERED, or PARTIALLY_DELIVERED orders can be sourced"
                )
                return

            try:
                se = SourcingEngine(session)
                sourcing_result = await se.source_order(order)

                if sourcing_result.total_split_nodes == 0:
                    # No inventory available — move to BACKORDERED
                    order.status = OrderStatus.BACKORDERED
                    if not order.backordered_since:
                        order.backordered_since = datetime.utcnow()
                    await session.commit()
                    logger.warning(
                        f"Order {order_id} moved to BACKORDERED — no inventory available"
                    )
                    try:
                        from motor.motor_asyncio import AsyncIOMotorClient
                        _mc = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000, uuidRepresentation="standard")
                        try:
                            await _mc[mongo_events_db].order_events.insert_one({
                                "order_id": order_id,
                                "event_type": "order.backordered",
                                "timestamp": datetime.utcnow(),
                                "data": {
                                    "reason": "No fulfillment nodes with sufficient inventory",
                                    "strategy": sourcing_result.strategy_used.value,
                                    "rule_applied": sourcing_result.rule_applied,
                                    "candidates_evaluated": sourcing_result.candidates_evaluated,
                                },
                            })
                        finally:
                            _mc.close()
                    except Exception:
                        pass
                    return

                await session.commit()
                logger.info(f"Order {order_id} sourced: {sourcing_result.total_split_nodes} nodes")

                # Log full sourcing decision to MongoDB audit trail
                try:
                    from motor.motor_asyncio import AsyncIOMotorClient
                    _mc = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000, uuidRepresentation="standard")
                    try:
                        _db = _mc[mongo_events_db]
                        await _db.order_events.insert_one({
                            "order_id": order_id,
                            "event_type": "order.sourced",
                            "timestamp": datetime.utcnow(),
                            "data": {
                                "strategy": sourcing_result.strategy_used.value,
                                "rule_applied": sourcing_result.rule_applied,
                                "total_nodes": sourcing_result.total_split_nodes,
                                "sourcing_score": sourcing_result.sourcing_score,
                                "processing_time_ms": sourcing_result.processing_time_ms,
                                "allocations": sourcing_result.allocations,
                                "rule_details": sourcing_result.rule_details,
                                "candidates_evaluated": sourcing_result.candidates_evaluated,
                            },
                        })
                    finally:
                        _mc.close()
                except Exception as mongo_exc:
                    logger.warning(f"Failed to log sourcing event to MongoDB: {mongo_exc}")

                # Write sourcing_outcomes skeleton docs for AI learning pipeline
                try:
                    from motor.motor_asyncio import AsyncIOMotorClient
                    _mc2 = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000, uuidRepresentation="standard")
                    try:
                        _db2 = _mc2[mongo_ai_db]  # AI learning DB
                        sourced_at = datetime.utcnow()

                        # Compute cluster key for pattern matching
                        amount = float(order.total_amount or 0)
                        if amount < 50:
                            amount_bucket = "0-50"
                        elif amount < 100:
                            amount_bucket = "50-100"
                        elif amount < 250:
                            amount_bucket = "100-250"
                        elif amount < 500:
                            amount_bucket = "250-500"
                        else:
                            amount_bucket = "500+"

                        channel = order.channel.value if hasattr(order.channel, "value") else str(order.channel)
                        region = order.shipping_state or "UNKNOWN"
                        fulfillment_type = (
                            order.fulfillment_type.value
                            if hasattr(order.fulfillment_type, "value")
                            else str(order.fulfillment_type or "SHIP_TO_HOME")
                        )
                        brand_slug = "default"
                        if getattr(order, "brand_id", None):
                            from app.models.postgres.brand_models import Brand
                            _brand_obj = await session.get(Brand, order.brand_id)
                            brand_slug = _brand_obj.slug if _brand_obj else "default"
                        cluster_key = f"{brand_slug}|{channel}|{region}|{amount_bucket}|{fulfillment_type}"

                        # Build a lookup dict from candidates_evaluated for extra node data
                        candidates_by_node: dict = {}
                        for cand in (sourcing_result.candidates_evaluated or []):
                            nid = cand.get("node_id")
                            if nid:
                                candidates_by_node[str(nid)] = cand

                        # One sourcing_outcomes doc per allocation
                        outcome_docs = []
                        for alloc in (sourcing_result.allocations or []):
                            alloc_node_id = str(alloc.get("node_id", ""))
                            cand_data = candidates_by_node.get(alloc_node_id, {})
                            outcome_docs.append({
                                "order_id": str(order_id),
                                "allocation_id": str(alloc.get("allocation_id", "")),
                                "node_id": alloc_node_id,
                                "node_name": alloc.get("node_name") or cand_data.get("node_name"),
                                "sku": alloc.get("sku"),
                                "strategy_used": sourcing_result.strategy_used.value,
                                "rule_applied": sourcing_result.rule_applied,
                                "sourcing_score": cand_data.get("score") or sourcing_result.sourcing_score,
                                "predicted_cost": cand_data.get("estimated_cost"),
                                "predicted_distance_miles": cand_data.get("distance_miles"),
                                "brand_id": str(order.brand_id) if getattr(order, "brand_id", None) else None,
                                "brand_slug": brand_slug,
                                "channel": channel,
                                "region": region,
                                "amount_bucket": amount_bucket,
                                "fulfillment_type": fulfillment_type,
                                "cluster_key": cluster_key,
                                "sourced_at": sourced_at.isoformat(),
                                "experiment_id": sourcing_result.experiment_id,
                                # Filled in later by carrier / learning workers:
                                # actual_delivery_hours, actual_cost, cost_variance_pct
                                # was_backordered, was_returned
                                # outcome_score, labeled_at
                            })

                        if outcome_docs:
                            await _db2.sourcing_outcomes.insert_many(outcome_docs)
                    finally:
                        _mc2.close()
                except Exception as learn_exc:
                    logger.warning(f"Failed to write sourcing_outcomes for order {order_id}: {learn_exc}")

                # Trigger picking
                celery_app.send_task(
                    "app.workers.fulfillment.start_picking",
                    args=[order_id, environment_id],
                    queue="fulfillment",
                    countdown=2,
                )

            except Exception as exc:
                logger.exception(f"Sourcing failed for order {order_id}: {exc}")

                # Capture to monitoring
                from app.services.monitoring import capture_error, SOURCE_SOURCING
                try:
                    await capture_error(exc, SOURCE_SOURCING,
                        task_context={"task": "source_order", "queue": "sourcing"},
                        order_context={"order_id": order_id})
                except Exception:
                    pass

                # Log sourcing failure to MongoDB audit trail
                try:
                    from motor.motor_asyncio import AsyncIOMotorClient
                    _mc = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=5000, uuidRepresentation="standard")
                    try:
                        await _mc[mongo_events_db].order_events.insert_one({
                            "order_id": order_id,
                            "event_type": "order.sourcing_failed",
                            "timestamp": datetime.utcnow(),
                            "data": {"error": str(exc)},
                        })
                    finally:
                        _mc.close()
                except Exception:
                    pass

                await session.rollback()
                raise self.retry(exc=exc)

        await engine.dispose()

    asyncio.run(_run())


@celery_app.task(
    name="app.workers.sourcing.retry_backordered_orders",
    queue="sourcing",
)
def retry_backordered_orders(environment_id: str = ""):
    """
    Periodic task: re-enqueue sourcing for BACKORDERED orders or orders with backorder line items.
    Checks both order status and order_items.quantity_backordered > 0.
    Orders older than BACKORDER_MAX_AGE_HOURS are left for manual admin review.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import settings
    from app.models.postgres import (  # noqa: register all mappers Order references
        order_models, inventory_models, node_models, sourcing_rule_models,
        connector_models, auth_models, lifecycle_models, b2b_models, brand_models,
    )
    from app.models.postgres.order_models import Order, OrderStatus, OrderItem
    from app.workers.env_utils import get_env_db_url
    import re

    sync_db_url = re.sub(r"\+asyncpg", "", get_env_db_url(environment_id))
    engine = create_engine(sync_db_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        cutoff = datetime.utcnow() - timedelta(hours=settings.BACKORDER_MAX_AGE_HOURS)
        
        # Find orders with backordered items using two queries to avoid complex WHERE clause issues
        
        # Query 1: Orders in BACKORDERED status within the retry window.
        # Exclude B2B orders still awaiting approval.
        from app.models.postgres.order_models import ApprovalStatus
        backordered_orders = session.query(Order).filter(
            Order.status == OrderStatus.BACKORDERED,
            Order.backordered_since >= cutoff,
            Order.approval_status != ApprovalStatus.PENDING.value,
        ).all()
        
        # Query 2: Orders with line items that have quantity_backordered > 0
        orders_with_backorder_items = session.query(Order.id).join(
            OrderItem, Order.id == OrderItem.order_id
        ).filter(
            OrderItem.quantity_backordered > 0
        ).distinct().all()
        
        order_ids_to_process = set()
        for order in backordered_orders:
            order_ids_to_process.add(order.id)
        for (order_id,) in orders_with_backorder_items:
            order_ids_to_process.add(order_id)
        
        if not order_ids_to_process:
            logger.info("retry_backordered_orders: no eligible backordered orders")
            return
        
        # Fetch full order objects and sort by creation date (FIFO)
        orders_to_process = session.query(Order).filter(
            Order.id.in_(list(order_ids_to_process))
        ).order_by(Order.created_at).all()
        
        logger.info(f"retry_backordered_orders: re-enqueueing {len(orders_to_process)} orders for partial backorder resolution")
        for order in orders_to_process:
            logger.info(f"Queuing source_order for order {order.order_number} (id={order.id})")
            source_order.delay(order.id, environment_id)
            
    except Exception as e:
        logger.error(f"Error in retry_backordered_orders: {str(e)}", exc_info=True)
    finally:
        session.close()
        engine.dispose()


@celery_app.task(
    name="app.workers.sourcing.source_pending_orders",
    queue="sourcing",
)
def source_pending_orders(environment_id: str = ""):
    """
    Periodic task: discover and source any CONFIRMED orders that haven't been sourced yet.
    This acts as a safety net for orders that may have slipped through the initial sourcing trigger.
    Processes orders in FIFO order (oldest first).
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import settings
    from app.models.postgres import (  # noqa: register all mappers Order references
        order_models, inventory_models, node_models, sourcing_rule_models,
        connector_models, auth_models, lifecycle_models, b2b_models, brand_models,
    )
    from app.models.postgres.order_models import Order, OrderStatus, FulfillmentAllocation
    from app.workers.env_utils import get_env_db_url
    import re

    sync_db_url = re.sub(r"\+asyncpg", "", get_env_db_url(environment_id))
    engine = create_engine(sync_db_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Find orders in CONFIRMED status that have no allocations yet (i.e., not yet sourced).
        # Exclude orders still awaiting B2B approval — they must not be sourced until approved.
        from app.models.postgres.order_models import ApprovalStatus
        confirmed_unsourced = session.query(Order).filter(
            Order.status == OrderStatus.CONFIRMED,
            Order.approval_status != ApprovalStatus.PENDING.value,
        ).order_by(Order.created_at).limit(50).all()
        
        # Further filter: only source if no successful allocations exist
        orders_to_source = []
        for order in confirmed_unsourced:
            # Check if order has any allocations
            has_allocations = session.query(FulfillmentAllocation).filter(
                FulfillmentAllocation.order_id == order.id
            ).first()
            if not has_allocations:
                orders_to_source.append(order)
        
        if not orders_to_source:
            logger.debug("source_pending_orders: no unsourced confirmed orders found")
            return
        
        logger.info(f"source_pending_orders: found {len(orders_to_source)} unsourced confirmed orders")
        for order in orders_to_source:
            logger.info(f"Queuing source_order for unsourced order {order.order_number} (id={order.id})")
            source_order.delay(order.id, environment_id)
            
    except Exception as e:
        logger.error(f"Error in source_pending_orders: {str(e)}", exc_info=True)
    finally:
        session.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Fan-out beat tasks — dispatch per-environment work
# ---------------------------------------------------------------------------

@celery_app.task(
    name="app.workers.sourcing.source_pending_orders_fanout",
    queue="sourcing",
)
def source_pending_orders_fanout():
    """Beat task: dispatch source_pending_orders to every active environment."""
    from app.workers.env_utils import list_active_environment_ids
    for env_id in list_active_environment_ids():
        source_pending_orders.delay(env_id)


@celery_app.task(
    name="app.workers.sourcing.retry_backordered_orders_fanout",
    queue="sourcing",
)
def retry_backordered_orders_fanout():
    """Beat task: dispatch retry_backordered_orders to every active environment."""
    from app.workers.env_utils import list_active_environment_ids
    for env_id in list_active_environment_ids():
        retry_backordered_orders.delay(env_id)
