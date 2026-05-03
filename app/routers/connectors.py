"""Connectors router — CRUD management + inbound webhook receiver."""
import json
import logging
import secrets
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.postgres import get_db
from app.dependencies.auth import require_superadmin
from app.models.postgres.connector_models import (
    Connector, ConnectorEvent, ConnectorStatus, ConnectorType,
)
from app.models.postgres.order_models import Order, OrderItem, OrderStatus, FulfillmentType, OrderChannel
from app.schemas.connectors import (
    ConnectorCreate, ConnectorUpdate, ConnectorResponse,
    ConnectorEventResponse, ConnectorTestResult, ConnectorToggleResponse,
)
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/connectors", tags=["Connectors"])


def _webhook_url(connector_id) -> str:
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    return f"{base}/connectors/{connector_id}/webhook"


def _to_response(connector: Connector) -> ConnectorResponse:
    r = ConnectorResponse.model_validate(connector)
    r.webhook_url = _webhook_url(connector.id)
    return r


# ─── CRUD Endpoints ───────────────────────────────────────────────────────────

@router.post("/", response_model=ConnectorResponse, status_code=201)
async def create_connector(
    payload: ConnectorCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    """Create a new connector integration. Starts in INACTIVE status."""
    connector = Connector(
        name=payload.name,
        connector_type=payload.connector_type,
        direction=payload.direction,
        status=ConnectorStatus.INACTIVE,
        config=payload.config or {},
    )
    db.add(connector)
    await db.flush()
    await db.refresh(connector)
    return _to_response(connector)


@router.get("/", response_model=list[ConnectorResponse])
async def list_connectors(
    status: Optional[ConnectorStatus] = None,
    connector_type: Optional[ConnectorType] = None,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    """List all connectors, optionally filtered by status or type."""
    q = select(Connector).order_by(Connector.created_at.desc())
    if status:
        q = q.where(Connector.status == status)
    if connector_type:
        q = q.where(Connector.connector_type == connector_type)
    result = await db.execute(q)
    return [_to_response(c) for c in result.scalars().all()]


@router.get("/{connector_id}", response_model=ConnectorResponse)
async def get_connector(
    connector_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    connector = await db.get(Connector, connector_id)
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    return _to_response(connector)


@router.patch("/{connector_id}", response_model=ConnectorResponse)
async def update_connector(
    connector_id: UUID,
    payload: ConnectorUpdate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    connector = await db.get(Connector, connector_id)
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")

    if payload.name is not None:
        connector.name = payload.name
    if payload.direction is not None:
        connector.direction = payload.direction
    if payload.status is not None:
        connector.status = payload.status
    if payload.config is not None:
        # Merge: preserve existing keys unless overwritten (so masked "***" values are skipped)
        existing = connector.config or {}
        for k, v in payload.config.items():
            if v != "***":  # skip masked placeholders
                existing[k] = v
        connector.config = existing

    await db.flush()
    await db.refresh(connector)
    return _to_response(connector)


@router.delete("/{connector_id}", status_code=204)
async def delete_connector(
    connector_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    connector = await db.get(Connector, connector_id)
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    await db.delete(connector)


@router.post("/{connector_id}/toggle", response_model=ConnectorToggleResponse)
async def toggle_connector(
    connector_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    """Toggle connector between ACTIVE and INACTIVE."""
    connector = await db.get(Connector, connector_id)
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")

    if connector.status == ConnectorStatus.ACTIVE:
        connector.status = ConnectorStatus.INACTIVE
    else:
        connector.status = ConnectorStatus.ACTIVE
        connector.last_error = None  # clear error on re-activation

    await db.flush()
    await db.refresh(connector)
    return ConnectorToggleResponse(id=connector.id, status=connector.status)


@router.post("/{connector_id}/test", response_model=ConnectorTestResult)
async def test_connector(
    connector_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    """Test connectivity and credentials for the connector."""
    from app.services.connectors.registry import get_connector

    connector = await db.get(Connector, connector_id)
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")

    try:
        impl = get_connector(connector)
        result = await impl.test_connection()
        return ConnectorTestResult(
            success=result.get("success", False),
            message=result.get("message", ""),
            details=result.get("details"),
        )
    except ValueError as exc:
        return ConnectorTestResult(
            success=False,
            message=str(exc),
            details=None,
        )


@router.post("/generate-secret", include_in_schema=True)
async def generate_webhook_secret(_: dict = Depends(require_superadmin)):
    """Generate a random webhook secret for connector configuration."""
    return {"secret": secrets.token_hex(32)}


@router.get("/{connector_id}/events", response_model=list[ConnectorEventResponse])
async def list_connector_events(
    connector_id: UUID,
    direction: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_superadmin),
):
    """Paginated event log for a connector."""
    connector = await db.get(Connector, connector_id)
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")

    q = (
        select(ConnectorEvent)
        .where(ConnectorEvent.connector_id == connector_id)
        .order_by(ConnectorEvent.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if direction:
        q = q.where(ConnectorEvent.direction == direction)
    if status:
        q = q.where(ConnectorEvent.status == status)

    result = await db.execute(q)
    return result.scalars().all()


# ─── Inbound Webhook Receiver (PUBLIC — HMAC authenticated) ──────────────────

@router.post("/{connector_id}/webhook", include_in_schema=True)
async def receive_webhook(
    connector_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Receive inbound webhooks from external platforms (e.g. Shopify orders/create).
    This endpoint is PUBLIC — authentication is via HMAC signature validation.
    """
    from app.services.connectors.registry import get_connector

    # Read raw body BEFORE any parsing (needed for HMAC)
    raw_body = await request.body()
    headers = dict(request.headers)

    # Load connector
    connector = await db.get(Connector, connector_id)
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")

    if connector.status == ConnectorStatus.INACTIVE:
        raise HTTPException(status_code=404, detail="Connector is inactive")

    # Validate HMAC / signature
    try:
        impl = get_connector(connector)
    except ValueError as exc:
        logger.error("receive_webhook: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))

    if not impl.validate_webhook(headers, raw_body):
        logger.warning("receive_webhook: invalid signature for connector %s", connector_id)
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Parse payload
    try:
        payload = json.loads(raw_body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = impl.get_event_type(headers)
    logger.info("receive_webhook: connector=%s topic=%s", connector_id, event_type)

    # Handle order creation topics
    if event_type in impl.get_inbound_topics():
        background_tasks.add_task(
            _process_inbound_order,
            connector_id=str(connector_id),
            payload=payload,
            event_type=event_type,
        )
    # Handle product / catalog sync topics
    elif event_type in impl.get_product_topics():
        background_tasks.add_task(
            _process_inbound_product,
            connector_id=str(connector_id),
            payload=payload,
            event_type=event_type,
        )

    return {"received": True, "event_type": event_type}


async def _process_inbound_order(connector_id: str, payload: dict, event_type: str) -> None:
    """
    Background task: normalize inbound webhook payload and create an OMS order.
    Handles deduplication: skips if external_order_id already exists for this connector.
    """
    from app.services.connectors.registry import get_connector
    from app.routers.orders import _generate_order_number, _log_order_event, _trigger_sourcing, _index_order_in_es

    async with async_session_factory() as db:
        connector = await db.get(Connector, UUID(connector_id))
        if not connector:
            return

        impl = get_connector(connector)

        # Normalize platform payload → OMS order dict
        try:
            order_data = impl.normalize_order(payload)
        except Exception as exc:
            logger.exception("_process_inbound_order: normalize_order failed for connector %s", connector_id)
            _log_event = ConnectorEvent(
                connector_id=connector.id,
                event_type=event_type,
                direction="inbound",
                status="failed",
                payload=payload,
                error_message=f"normalize_order failed: {exc}",
            )
            db.add(_log_event)
            await db.commit()
            from app.services.monitoring import capture_error, SOURCE_CONNECTOR
            await capture_error(exc, SOURCE_CONNECTOR,
                task_context={"task": "_process_inbound_order", "event_type": event_type},
                extra={"connector_id": connector_id, "stage": "normalize_order"})
            return

        external_order_id = order_data.get("external_order_id")

        # Deduplication: skip if this external order was already imported for this connector
        if external_order_id:
            existing = await db.execute(
                select(Order).where(
                    Order.external_order_id == external_order_id,
                    Order.connector_id == connector.id,
                )
            )
            if existing.scalar_one_or_none():
                logger.info(
                    "_process_inbound_order: duplicate external_order_id=%s for connector=%s, skipping",
                    external_order_id, connector_id,
                )
                return

        # Build the OMS Order object from normalized data
        try:
            line_items_data = order_data.pop("line_items", [])
            shipping_addr = order_data.pop("shipping_address", None)

            subtotal = sum(
                (float(item.get("unit_price", 0)) * int(item.get("quantity", 1)))
                - float(item.get("discount_amount", 0))
                for item in line_items_data
            )
            tax_amount = sum(
                float(item.get("tax_amount", 0)) * int(item.get("quantity", 1))
                for item in line_items_data
            )
            shipping_amount = float(order_data.get("shipping_amount", 0))
            discount_amount = float(order_data.get("discount_amount", 0))
            total = subtotal + tax_amount + shipping_amount - discount_amount

            order = Order(
                order_number=_generate_order_number(),
                channel=OrderChannel.MARKETPLACE,
                fulfillment_type=FulfillmentType(order_data.get("fulfillment_type", "SHIP_TO_HOME")),
                status=OrderStatus.PENDING,
                customer_email=order_data["customer_email"],
                customer_name=order_data.get("customer_name"),
                customer_phone=order_data.get("customer_phone"),
                customer_id=order_data.get("customer_id"),
                subtotal=subtotal,
                tax_amount=tax_amount,
                shipping_amount=shipping_amount,
                discount_amount=discount_amount,
                total_amount=total,
                currency=order_data.get("currency", "USD"),
                external_order_id=external_order_id,
                connector_id=connector.id,
                tags=order_data.get("tags", []),
                notes=order_data.get("notes"),
                metadata_=order_data.get("metadata", {}),
            )

            if shipping_addr:
                order.shipping_name = shipping_addr.get("name")
                order.shipping_address1 = shipping_addr.get("address1", "")
                order.shipping_address2 = shipping_addr.get("address2")
                order.shipping_city = shipping_addr.get("city", "")
                order.shipping_state = shipping_addr.get("state", "")
                order.shipping_postal_code = shipping_addr.get("postal_code", "")
                order.shipping_country = shipping_addr.get("country", "US")

            db.add(order)
            await db.flush()

            # Create line items
            for item_data in line_items_data:
                item_total = (
                    float(item_data.get("unit_price", 0)) * int(item_data.get("quantity", 1))
                    - float(item_data.get("discount_amount", 0))
                    + float(item_data.get("tax_amount", 0)) * int(item_data.get("quantity", 1))
                )
                item = OrderItem(
                    order_id=order.id,
                    sku=item_data["sku"],
                    product_name=item_data["product_name"],
                    quantity=int(item_data.get("quantity", 1)),
                    unit_price=float(item_data.get("unit_price", 0)),
                    discount_amount=float(item_data.get("discount_amount", 0)),
                    tax_amount=float(item_data.get("tax_amount", 0)),
                    total_price=item_total,
                    weight_lbs=float(item_data.get("weight_lbs", 0)),
                    metadata_=item_data.get("metadata", {}),
                )
                db.add(item)

            await db.flush()

            # Log successful import
            event = ConnectorEvent(
                connector_id=connector.id,
                order_id=order.id,
                external_order_id=external_order_id,
                event_type=event_type,
                direction="inbound",
                status="success",
                payload={"shopify_order_id": external_order_id, "event": event_type},
            )
            db.add(event)
            connector.orders_received = (connector.orders_received or 0) + 1
            connector.last_synced_at = datetime.utcnow()

            await db.commit()
            await db.refresh(order)

            # Fire background tasks (ES index, MongoDB audit, sourcing)
            try:
                await _log_order_event(str(order.id), "order.created", {
                    "order_number": order.order_number,
                    "channel": order.channel.value,
                    "total_amount": float(order.total_amount),
                    "source": "connector",
                    "connector_id": connector_id,
                    "external_order_id": external_order_id,
                })
            except Exception:
                pass

            try:
                await _index_order_in_es(order)
            except Exception:
                pass

            try:
                await _trigger_sourcing(str(order.id))
            except Exception:
                pass

            logger.info(
                "_process_inbound_order: created order %s (external=%s) from connector %s",
                order.order_number, external_order_id, connector_id,
            )

        except Exception as exc:
            logger.exception(
                "_process_inbound_order: failed to create order for connector %s, external=%s",
                connector_id, external_order_id,
            )
            event = ConnectorEvent(
                connector_id=connector.id,
                external_order_id=external_order_id,
                event_type=event_type,
                direction="inbound",
                status="failed",
                payload={"shopify_order_id": external_order_id},
                error_message=str(exc),
            )
            db.add(event)
            connector.status = ConnectorStatus.ERROR
            connector.last_error = str(exc)
            connector.last_error_at = datetime.utcnow()
            await db.commit()
            from app.services.monitoring import capture_error, SOURCE_CONNECTOR
            await capture_error(exc, SOURCE_CONNECTOR,
                task_context={"task": "_process_inbound_order", "event_type": event_type},
                extra={"connector_id": connector_id, "external_order_id": external_order_id, "stage": "create_order"})


async def _process_inbound_product(connector_id: str, payload: dict, event_type: str) -> None:
    """
    Background task: normalize Shopify products/create or products/update payload
    and upsert InventoryItem records across all active fulfillment nodes.

    Strategy:
      - New (node, sku) pairs   → INSERT with initial stock from Shopify inventory_quantity
      - Existing (node, sku)    → UPDATE product_name, unit_cost, weight_lbs, is_active only
                                  (stock levels are left unchanged — OMS is system of record)
    """
    from app.services.connectors.registry import get_connector
    from app.models.postgres.inventory_models import InventoryItem
    from app.models.postgres.node_models import FulfillmentNode, NodeStatus
    from sqlalchemy import select, tuple_

    async with async_session_factory() as db:
        connector = await db.get(Connector, UUID(connector_id))
        if not connector:
            return

        impl = get_connector(connector)

        # Normalize payload → list of variant dicts
        try:
            variants = impl.normalize_product(payload)
        except Exception as exc:
            logger.exception("_process_inbound_product: normalize_product failed for connector %s", connector_id)
            event = ConnectorEvent(
                connector_id=connector.id,
                event_type=event_type,
                direction="inbound",
                status="failed",
                payload={"shopify_product_id": payload.get("id")},
                error_message=f"normalize_product failed: {exc}",
            )
            db.add(event)
            await db.commit()
            from app.services.monitoring import capture_error, SOURCE_CONNECTOR
            await capture_error(exc, SOURCE_CONNECTOR,
                task_context={"task": "_process_inbound_product", "event_type": event_type},
                extra={"connector_id": connector_id, "stage": "normalize_product"})
            return

        if not variants:
            logger.info("_process_inbound_product: no variants in payload, nothing to do")
            return

        # Load all active fulfillment nodes
        nodes_result = await db.execute(
            select(FulfillmentNode).where(FulfillmentNode.status == NodeStatus.ACTIVE)
        )
        nodes = nodes_result.scalars().all()
        if not nodes:
            logger.warning("_process_inbound_product: no active nodes found — skipping inventory sync")
            return

        skus = [v["sku"] for v in variants]
        node_ids = [n.id for n in nodes]

        # Fetch all existing (node_id, sku) combinations in one query
        existing_result = await db.execute(
            select(InventoryItem).where(
                InventoryItem.node_id.in_(node_ids),
                InventoryItem.sku.in_(skus),
            )
        )
        existing_items = existing_result.scalars().all()
        existing_map = {(str(item.node_id), item.sku): item for item in existing_items}

        created = 0
        updated = 0
        new_items: list[tuple] = []  # (InventoryItem, variant_dict) for newly created

        for node in nodes:
            for variant in variants:
                sku = variant["sku"]
                key = (str(node.id), sku)

                if key in existing_map:
                    # Update catalog metadata only — don't touch stock quantities
                    item = existing_map[key]
                    item.product_name = variant["product_name"]
                    item.unit_cost = variant["unit_cost"]
                    item.weight_lbs = variant["weight_lbs"]
                    item.is_active = variant["is_active"]
                    updated += 1
                else:
                    # New SKU for this node — seed with Shopify's inventory_quantity
                    qty = variant["quantity"]
                    item = InventoryItem(
                        node_id=node.id,
                        sku=sku,
                        product_name=variant["product_name"],
                        quantity_on_hand=qty,
                        quantity_reserved=0,
                        quantity_available=qty,
                        quantity_on_order=0,
                        unit_cost=variant["unit_cost"],
                        weight_lbs=variant["weight_lbs"],
                        is_active=variant["is_active"],
                    )
                    db.add(item)
                    new_items.append((item, variant))
                    created += 1

        # Flush to assign IDs to newly created InventoryItems
        await db.flush()

        # Upsert ConnectorInventoryMapping for each newly created item
        if new_items:
            from app.models.postgres.connector_models import ConnectorInventoryMapping
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            primary_location_id = str(connector.config.get("primary_location_id") or "") or None

            for item, variant in new_items:
                shopify_inv_item_id = str(variant.get("shopify_inventory_item_id") or "")
                if not shopify_inv_item_id:
                    continue
                stmt = pg_insert(ConnectorInventoryMapping).values(
                    connector_id=connector.id,
                    inventory_item_id=item.id,
                    sku=variant["sku"],
                    shopify_inventory_item_id=shopify_inv_item_id,
                    shopify_location_id=primary_location_id,
                    platform_sku=variant["sku"],
                ).on_conflict_do_update(
                    constraint="uq_connector_inventory_mapping",
                    set_={
                        "shopify_inventory_item_id": shopify_inv_item_id,
                        "shopify_location_id": primary_location_id,
                    }
                )
                await db.execute(stmt)

        # Log ConnectorEvent
        event = ConnectorEvent(
            connector_id=connector.id,
            event_type=event_type,
            direction="inbound",
            status="success",
            payload={
                "shopify_product_id": payload.get("id"),
                "shopify_product_title": payload.get("title"),
                "variants_count": len(variants),
            },
            response={
                "nodes": len(nodes),
                "skus_created": created,
                "skus_updated": updated,
            },
        )
        db.add(event)
        connector.orders_received = (connector.orders_received or 0) + 1
        connector.last_synced_at = datetime.utcnow()
        await db.commit()

        logger.info(
            "_process_inbound_product: connector=%s product=%s variants=%d nodes=%d created=%d updated=%d",
            connector_id, payload.get("id"), len(variants), len(nodes), created, updated,
        )


# Import needed for _process_inbound_order helper
from app.database.postgres import async_session_factory  # noqa: E402
