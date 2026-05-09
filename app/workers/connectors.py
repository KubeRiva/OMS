"""Celery worker: outbound fulfillment sync to external connectors."""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.workers.celery_app import celery_app
from app.models.postgres.connector_models import (
    Connector, ConnectorEvent, ConnectorStatus, ConnectorType,
)
from app.models.postgres.order_models import Order
# Register all mappers Order depends on (brand_id/seller_brand_id relationships)
import app.models.postgres.brand_models      # noqa: F401
import app.models.postgres.b2b_models        # noqa: F401
import app.models.postgres.auth_models       # noqa: F401
import app.models.postgres.node_models       # noqa: F401
import app.models.postgres.sourcing_rule_models  # noqa: F401

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _get_session():
    """Create a fresh DB session bound to the current event loop (safe for asyncio.run())."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from app.config import settings
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


async def _async_sync_fulfillment(order_id: str) -> None:
    """Core async logic for pushing fulfillment to the source connector."""
    from app.services.connectors.registry import get_connector

    async with _get_session() as db:
        # Load order with shipments
        result = await db.execute(
            select(Order)
            .options(selectinload(Order.shipments))
            .where(Order.id == UUID(order_id))
        )
        order = result.scalar_one_or_none()

        if not order:
            logger.warning("sync_fulfillment: order %s not found", order_id)
            return

        if not order.connector_id:
            logger.debug("sync_fulfillment: order %s has no connector_id, skipping", order_id)
            return

        connector = await db.get(Connector, order.connector_id)
        if not connector:
            logger.warning("sync_fulfillment: connector %s not found", order.connector_id)
            return

        if connector.status != ConnectorStatus.ACTIVE:
            logger.info("sync_fulfillment: connector %s is %s, skipping", connector.id, connector.status)
            return

        # Find the most recent shipment with a tracking number
        shipped = [s for s in (order.shipments or []) if s.tracking_number]
        if not shipped:
            logger.info("sync_fulfillment: order %s has no shipment with tracking, skipping", order_id)
            return
        shipment = shipped[-1]

        # Get the connector implementation
        try:
            impl = get_connector(connector)
        except ValueError as exc:
            logger.error("sync_fulfillment: %s", exc)
            return

        # Push fulfillment to the external platform
        try:
            response = await impl.push_fulfillment(order, shipment)
            event = ConnectorEvent(
                connector_id=connector.id,
                order_id=order.id,
                external_order_id=order.external_order_id,
                event_type="fulfillment.pushed",
                direction="outbound",
                status="success",
                payload={
                    "order_id": str(order.id),
                    "order_number": order.order_number,
                    "tracking_number": shipment.tracking_number,
                },
                response=response,
            )
            db.add(event)
            connector.orders_synced = (connector.orders_synced or 0) + 1
            connector.last_synced_at = datetime.utcnow()
            await db.commit()
            logger.info("sync_fulfillment: pushed fulfillment for order %s to connector %s", order_id, connector.id)

        except Exception as exc:
            logger.exception("sync_fulfillment: failed for order %s on connector %s", order_id, connector.id)
            event = ConnectorEvent(
                connector_id=connector.id,
                order_id=order.id,
                external_order_id=order.external_order_id,
                event_type="fulfillment.pushed",
                direction="outbound",
                status="failed",
                payload={
                    "order_id": str(order.id),
                    "order_number": order.order_number,
                    "tracking_number": shipment.tracking_number,
                },
                error_message=str(exc),
            )
            db.add(event)
            connector.status = ConnectorStatus.ERROR
            connector.last_error = str(exc)
            connector.last_error_at = datetime.utcnow()
            await db.commit()


@celery_app.task(
    name="app.workers.connectors.sync_fulfillment",
    bind=True,
    max_retries=3,
    default_retry_delay=120,
    acks_late=True,
    reject_on_worker_lost=True,
)
def sync_fulfillment_to_connector(self, order_id: str) -> None:
    """
    Push fulfillment/tracking update to the external connector platform
    when an OMS order transitions to SHIPPED status.
    """
    try:
        asyncio.run(_async_sync_fulfillment(order_id))
    except Exception as exc:
        logger.exception("sync_fulfillment_to_connector task failed for order %s", order_id)
        from app.services.monitoring import capture_error_sync, SOURCE_CONNECTOR
        capture_error_sync(exc, SOURCE_CONNECTOR,
            task_context={"task": "sync_fulfillment", "queue": "connectors", "retry": self.request.retries},
            order_context={"order_id": order_id})
        raise self.retry(exc=exc)


async def _async_sync_order_cancel(order_id: str) -> None:
    """Core async logic for pushing order cancellation to the source connector."""
    from app.services.connectors.registry import get_connector

    async with _get_session() as db:
        result = await db.execute(
            select(Order).where(Order.id == UUID(order_id))
        )
        order = result.scalar_one_or_none()

        if not order:
            logger.warning("sync_order_cancel: order %s not found", order_id)
            return

        if not order.connector_id:
            logger.debug("sync_order_cancel: order %s has no connector_id, skipping", order_id)
            return

        connector = await db.get(Connector, order.connector_id)
        if not connector:
            logger.warning("sync_order_cancel: connector %s not found", order.connector_id)
            return

        if connector.status != ConnectorStatus.ACTIVE:
            logger.info("sync_order_cancel: connector %s is %s, skipping", connector.id, connector.status)
            return

        try:
            impl = get_connector(connector)
        except ValueError as exc:
            logger.error("sync_order_cancel: %s", exc)
            return

        try:
            response = await impl.push_order_cancel(order)
            event = ConnectorEvent(
                connector_id=connector.id,
                order_id=order.id,
                external_order_id=order.external_order_id,
                event_type="order.cancelled",
                direction="outbound",
                status="success",
                payload={
                    "order_id": str(order.id),
                    "order_number": order.order_number,
                    "external_order_id": order.external_order_id,
                },
                response=response,
            )
            db.add(event)
            connector.orders_synced = (connector.orders_synced or 0) + 1
            connector.last_synced_at = datetime.utcnow()
            await db.commit()
            logger.info(
                "sync_order_cancel: pushed cancel for order %s to connector %s",
                order_id, connector.id,
            )

        except Exception as exc:
            logger.exception(
                "sync_order_cancel: failed for order %s on connector %s", order_id, connector.id
            )
            event = ConnectorEvent(
                connector_id=connector.id,
                order_id=order.id,
                external_order_id=order.external_order_id,
                event_type="order.cancelled",
                direction="outbound",
                status="failed",
                payload={
                    "order_id": str(order.id),
                    "order_number": order.order_number,
                },
                error_message=str(exc),
            )
            db.add(event)
            connector.status = ConnectorStatus.ERROR
            connector.last_error = str(exc)
            connector.last_error_at = datetime.utcnow()
            await db.commit()


@celery_app.task(
    name="app.workers.connectors.sync_order_cancel",
    bind=True,
    max_retries=3,
    default_retry_delay=120,
    acks_late=True,
    reject_on_worker_lost=True,
)
def sync_order_cancel_to_connector(self, order_id: str) -> None:
    """
    Push order cancellation to the external connector platform
    when an OMS order transitions to CANCELLED status.
    """
    try:
        asyncio.run(_async_sync_order_cancel(order_id))
    except Exception as exc:
        logger.exception("sync_order_cancel_to_connector task failed for order %s", order_id)
        from app.services.monitoring import capture_error_sync, SOURCE_CONNECTOR
        capture_error_sync(exc, SOURCE_CONNECTOR,
            task_context={"task": "sync_order_cancel", "queue": "connectors", "retry": self.request.retries},
            order_context={"order_id": order_id})
        raise self.retry(exc=exc)


# ─── Amazon SP-API: Order Polling ────────────────────────────────────────────

async def _async_poll_amazon_connector(connector_id: str) -> int:
    """
    Poll a single Amazon connector for new orders and create OMS orders.
    Returns the number of orders imported.
    """
    from app.services.connectors.registry import get_connector
    from app.services.connectors.amazon import AmazonSPConnector

    async with _get_session() as db:
        connector = await db.get(Connector, UUID(connector_id))
        if not connector or connector.status != ConnectorStatus.ACTIVE:
            return 0

        impl = get_connector(connector)
        if not isinstance(impl, AmazonSPConnector):
            return 0

        # Determine polling window: last_synced_at → now (or 20 min if never synced)
        from datetime import timezone, timedelta
        if connector.last_synced_at:
            created_after = connector.last_synced_at.replace(tzinfo=timezone.utc) - timedelta(seconds=30)
        else:
            created_after = datetime.now(timezone.utc) - timedelta(minutes=20)

        try:
            raw_orders = await impl.fetch_new_orders(created_after=created_after)
        except Exception as exc:
            logger.exception("poll_amazon: fetch_new_orders failed for connector %s", connector_id)
            connector.status = ConnectorStatus.ERROR
            connector.last_error = str(exc)
            connector.last_error_at = datetime.utcnow()
            await db.commit()
            from app.services.monitoring import capture_error, SOURCE_CONNECTOR
            await capture_error(exc, SOURCE_CONNECTOR,
                task_context={"task": "poll_amazon_orders", "connector_id": connector_id})
            return 0

        imported = 0
        from app.models.postgres.order_models import Order, OrderItem, OrderStatus, OrderChannel, FulfillmentType

        for raw_order in raw_orders:
            amazon_order_id = raw_order.get("AmazonOrderId", "")
            if not amazon_order_id:
                continue

            # Deduplication: skip if already imported
            from sqlalchemy import select as sa_select
            dup = await db.execute(
                sa_select(Order).where(
                    Order.external_order_id == amazon_order_id,
                    Order.connector_id == connector.id,
                )
            )
            if dup.scalar_one_or_none():
                logger.debug("poll_amazon: order %s already exists, skipping", amazon_order_id)
                continue

            # Fetch line items
            try:
                items = await impl.fetch_order_items(amazon_order_id)
            except Exception as exc:
                logger.warning("poll_amazon: fetch_order_items failed for %s: %s", amazon_order_id, exc)
                items = []

            raw_order["_line_items"] = items

            # Normalize to OMS format
            try:
                order_data = impl.normalize_order(raw_order)
            except Exception as exc:
                logger.exception("poll_amazon: normalize_order failed for %s", amazon_order_id)
                event = ConnectorEvent(
                    connector_id=connector.id,
                    external_order_id=amazon_order_id,
                    event_type="order.received",
                    direction="inbound",
                    status="failed",
                    payload={"amazon_order_id": amazon_order_id},
                    error_message=f"normalize_order: {exc}",
                )
                db.add(event)
                await db.commit()
                continue

            # Build OMS Order
            try:
                order_number = f"AMZ-{amazon_order_id[-6:]}"
                order = Order(
                    order_number=order_number,
                    channel=OrderChannel.MARKETPLACE,
                    status=OrderStatus.PENDING,
                    fulfillment_type=order_data.get("fulfillment_type", "SHIP_TO_HOME"),
                    customer_email=order_data["customer_email"],
                    customer_name=order_data.get("customer_name"),
                    customer_id=order_data.get("customer_id"),
                    customer_phone=order_data.get("customer_phone"),
                    shipping_address=order_data.get("shipping_address"),
                    currency=order_data.get("currency", "USD"),
                    shipping_amount=order_data.get("shipping_amount", 0),
                    discount_amount=order_data.get("discount_amount", 0),
                    external_order_id=amazon_order_id,
                    connector_id=connector.id,
                    brand_id=connector.brand_id,
                    tags=order_data.get("tags", []),
                    notes=order_data.get("notes"),
                    metadata_=order_data.get("metadata", {}),
                )
                db.add(order)
                await db.flush()

                for li in order_data.get("line_items", []):
                    item = OrderItem(
                        order_id=order.id,
                        sku=li["sku"],
                        product_name=li["product_name"],
                        quantity=li["quantity"],
                        unit_price=li["unit_price"],
                        discount_amount=li.get("discount_amount", 0),
                        tax_amount=li.get("tax_amount", 0),
                        weight_lbs=li.get("weight_lbs", 0),
                        metadata_=li.get("metadata", {}),
                    )
                    db.add(item)

                event = ConnectorEvent(
                    connector_id=connector.id,
                    order_id=order.id,
                    external_order_id=amazon_order_id,
                    event_type="order.received",
                    direction="inbound",
                    status="success",
                    payload={"amazon_order_id": amazon_order_id},
                    response={"order_id": str(order.id), "order_number": order_number},
                )
                db.add(event)
                connector.orders_received = (connector.orders_received or 0) + 1
                await db.commit()
                imported += 1
                logger.info("poll_amazon: imported order %s → OMS %s", amazon_order_id, order.id)

            except Exception as exc:
                logger.exception("poll_amazon: failed to create OMS order for %s", amazon_order_id)
                await db.rollback()
                event = ConnectorEvent(
                    connector_id=connector.id,
                    external_order_id=amazon_order_id,
                    event_type="order.received",
                    direction="inbound",
                    status="failed",
                    payload={"amazon_order_id": amazon_order_id},
                    error_message=str(exc),
                )
                db.add(event)
                await db.commit()

        # Update sync timestamp
        connector.last_synced_at = datetime.utcnow()
        await db.commit()
        return imported


async def _async_poll_all_amazon_connectors() -> int:
    """Poll all active Amazon SP connectors for new orders. Returns total imported."""
    async with _get_session() as db:
        result = await db.execute(
            select(Connector).where(
                Connector.connector_type == ConnectorType.AMAZON_SP,
                Connector.status == ConnectorStatus.ACTIVE,
            )
        )
        connectors = result.scalars().all()
        connector_ids = [str(c.id) for c in connectors]

    if not connector_ids:
        return 0  # No active Amazon connectors — nothing to do

    total = 0
    for cid in connector_ids:
        try:
            count = await _async_poll_amazon_connector(cid)
            total += count
            logger.info("poll_amazon: connector %s → %d orders imported", cid, count)
        except Exception:
            logger.exception("poll_amazon: unexpected error for connector %s", cid)
    return total


@celery_app.task(name="app.workers.connectors.poll_amazon_orders")
def poll_amazon_orders() -> None:
    """
    Beat task: runs every 15 minutes to poll all active Amazon SP-API connectors
    for new Unshipped/PartiallyShipped orders and import them into the OMS.
    """
    try:
        imported = asyncio.run(_async_poll_all_amazon_connectors())
        if imported:
            logger.info("poll_amazon_orders: imported %d orders total", imported)
    except Exception as exc:
        err_msg = str(exc)
        # Suppress noise when no connectors are configured — this is expected
        if "no active amazon" in err_msg.lower() or not err_msg:
            return
        logger.exception("poll_amazon_orders beat task failed")
        from app.services.monitoring import capture_error_sync, SOURCE_CONNECTOR
        capture_error_sync(exc, SOURCE_CONNECTOR,
            task_context={"task": "poll_amazon_orders", "queue": "connectors"})
