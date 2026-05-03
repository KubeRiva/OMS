"""Orders router — core order lifecycle management."""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload
from typing import Literal, Optional
from uuid import UUID
from pydantic import BaseModel
from datetime import datetime
from decimal import Decimal

from app.database.postgres import get_db
from app.dependencies.auth import get_current_user
from app.models.postgres.order_models import (
    Order, OrderItem, FulfillmentAllocation, Shipment,
    OrderStatus, PaymentStatus, OrderChannel, FulfillmentType
)
from app.schemas.orders import (
    OrderCreate, OrderUpdate, OrderResponse, OrderListResponse,
    OrderStatusUpdate, CancelOrderRequest, OrderFilterParams,
)

router = APIRouter(prefix="/orders", tags=["Orders"], dependencies=[Depends(get_current_user)])


def _generate_order_number() -> str:
    import random, string
    prefix = "ORD"
    ts = datetime.utcnow().strftime("%Y%m%d")
    rand = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"{prefix}-{ts}-{rand}"


async def _index_order_in_es(order: Order):
    """Index order in Elasticsearch (fire-and-forget)."""
    try:
        from app.database.elasticsearch_client import get_es_client, ORDER_INDEX
        es = await get_es_client()
        doc = {
            "id": str(order.id),
            "order_number": order.order_number,
            "channel": order.channel.value if order.channel else None,
            "status": order.status.value if order.status else None,
            "fulfillment_type": order.fulfillment_type.value if order.fulfillment_type else None,
            "customer_email": order.customer_email,
            "customer_name": order.customer_name,
            "total_amount": float(order.total_amount or 0),
            "currency": order.currency,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "updated_at": order.updated_at.isoformat() if order.updated_at else None,
            "shipping_city": order.shipping_city,
            "shipping_state": order.shipping_state,
            "shipping_country": order.shipping_country,
            "tags": order.tags or [],
        }
        await es.index(index=ORDER_INDEX, id=str(order.id), document=doc)
    except Exception:
        pass  # Non-blocking


async def _log_order_event(order_id: str, event_type: str, data: dict):
    """Append event to MongoDB audit trail."""
    try:
        from app.database.mongodb import get_mongo_db
        db = await get_mongo_db()
        await db.order_events.insert_one({
            "order_id": order_id,
            "event_type": event_type,
            "timestamp": datetime.utcnow(),
            "data": data,
        })
    except Exception:
        pass


@router.post("/", response_model=OrderResponse, status_code=201)
@limiter.limit("60/minute")
async def create_order(
    request: Request,
    payload: OrderCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # Calculate totals
    subtotal = sum(
        (item.unit_price * item.quantity) - item.discount_amount
        for item in payload.line_items
    )
    tax_amount = sum(item.tax_amount * item.quantity for item in payload.line_items)
    total = subtotal + tax_amount + payload.shipping_amount - payload.discount_amount

    # Resolve the lifecycle that governs this order's status transitions
    from app.services.lifecycle_engine import resolve_lifecycle
    lc, _ = await resolve_lifecycle(
        db,
        payload.fulfillment_type.value,
        payload.channel.value,
    )

    order = Order(
        order_number=_generate_order_number(),
        channel=payload.channel,
        fulfillment_type=payload.fulfillment_type,
        status=OrderStatus.CONFIRMED,
        customer_email=str(payload.customer_email),
        customer_phone=payload.customer_phone,
        customer_name=payload.customer_name,
        customer_id=payload.customer_id,
        subtotal=subtotal,
        tax_amount=tax_amount,
        shipping_amount=payload.shipping_amount,
        discount_amount=payload.discount_amount,
        total_amount=total,
        currency=payload.currency,
        pickup_node_id=payload.pickup_node_id,
        lifecycle_id=lc.id if lc else None,
        external_order_id=payload.external_order_id,
        tags=payload.tags,
        notes=payload.notes,
        metadata_=payload.metadata,
    )

    if payload.shipping_address:
        addr = payload.shipping_address
        order.shipping_name = addr.name
        order.shipping_address1 = addr.address1
        order.shipping_address2 = addr.address2
        order.shipping_city = addr.city
        order.shipping_state = addr.state
        order.shipping_postal_code = addr.postal_code
        order.shipping_country = addr.country
        order.shipping_latitude = addr.latitude
        order.shipping_longitude = addr.longitude

        # Geocode if coordinates not explicitly provided
        if addr.latitude is None or addr.longitude is None:
            try:
                from app.services.geocoding import geocode_address
                coords = await geocode_address(
                    postal_code=addr.postal_code or "",
                    city=addr.city or "",
                    state=addr.state or "",
                    country=addr.country or "US",
                )
                if coords:
                    order.shipping_latitude, order.shipping_longitude = coords
            except Exception:
                pass  # geocoding failure is non-fatal

    db.add(order)
    await db.flush()

    # Create line items
    for item_data in payload.line_items:
        item_total = (item_data.unit_price * item_data.quantity) - item_data.discount_amount + (item_data.tax_amount * item_data.quantity)
        item = OrderItem(
            order_id=order.id,
            sku=item_data.sku,
            product_name=item_data.product_name,
            quantity=item_data.quantity,
            unit_price=item_data.unit_price,
            discount_amount=item_data.discount_amount,
            tax_amount=item_data.tax_amount,
            total_price=item_total,
            weight_lbs=item_data.weight_lbs,
            metadata_=item_data.metadata,
        )
        db.add(item)

    await db.flush()
    await db.refresh(order)

    # Reload with relationships
    result = await db.execute(
        select(Order)
        .options(
            selectinload(Order.line_items),
            selectinload(Order.fulfillment_allocations).selectinload(FulfillmentAllocation.node),
            selectinload(Order.shipments),
        )
        .where(Order.id == order.id)
    )
    order = result.scalar_one()

    # Resolve environment_id from request state (set by EnvironmentMiddleware)
    env_id = getattr(request.state, "environment_id", "") or ""

    # Background: Elasticsearch + MongoDB + trigger sourcing + confirmation notification
    background_tasks.add_task(_index_order_in_es, order)
    background_tasks.add_task(_log_order_event, str(order.id), "order.created", {
        "order_number": order.order_number,
        "channel": order.channel.value,
        "total_amount": float(order.total_amount),
    })
    background_tasks.add_task(_trigger_sourcing, str(order.id), env_id)
    background_tasks.add_task(_trigger_order_confirmation, str(order.id))

    return order


async def _trigger_sourcing(order_id: str, environment_id: str = ""):
    """Enqueue sourcing task for the order."""
    try:
        from app.workers.celery_app import celery_app
        celery_app.send_task(
            "app.workers.sourcing.source_order",
            args=[order_id, environment_id],
            queue="sourcing",
        )
    except Exception:
        pass


async def _trigger_order_confirmation(order_id: str):
    """Enqueue order confirmation notification."""
    try:
        from app.workers.celery_app import celery_app
        celery_app.send_task(
            "app.workers.notifications.send_order_confirmation",
            args=[order_id],
            queue="notifications",
        )
    except Exception:
        pass


async def _trigger_cancellation_notification(order_id: str, reason: str):
    """Enqueue order cancellation notification."""
    try:
        from app.workers.celery_app import celery_app
        celery_app.send_task(
            "app.workers.notifications.send_cancellation_notification",
            args=[order_id, reason],
            queue="notifications",
        )
    except Exception:
        pass


@router.get("/", response_model=OrderListResponse)
async def list_orders(
    status: Optional[OrderStatus] = None,
    channel: Optional[OrderChannel] = None,
    fulfillment_type: Optional[FulfillmentType] = None,
    customer_email: Optional[str] = None,
    search: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(Order).options(
        selectinload(Order.line_items),
        selectinload(Order.fulfillment_allocations).selectinload(FulfillmentAllocation.node),
        selectinload(Order.shipments),
    )
    if status:
        query = query.where(Order.status == status)
    if channel:
        query = query.where(Order.channel == channel)
    if fulfillment_type:
        query = query.where(Order.fulfillment_type == fulfillment_type)
    if customer_email:
        query = query.where(Order.customer_email == customer_email)
    if search:
        pattern = f"%{search}%"
        from sqlalchemy import or_
        query = query.where(
            or_(
                Order.order_number.ilike(pattern),
                Order.customer_email.ilike(pattern),
                Order.customer_name.ilike(pattern),
            )
        )
    if from_date:
        query = query.where(Order.created_at >= from_date)
    if to_date:
        query = query.where(Order.created_at <= to_date)

    count_query = select(func.count()).select_from(
        select(Order.id)
        .where(*[c for c in query.whereclause.get_children()] if query.whereclause is not None else [])
        .subquery()
    )
    # Use simpler count
    count_result = await db.execute(select(func.count(Order.id)))
    # Re-apply filters for count
    count_q = select(func.count(Order.id))
    if status:
        count_q = count_q.where(Order.status == status)
    if channel:
        count_q = count_q.where(Order.channel == channel)
    if fulfillment_type:
        count_q = count_q.where(Order.fulfillment_type == fulfillment_type)
    if customer_email:
        count_q = count_q.where(Order.customer_email == customer_email)
    if search:
        pattern = f"%{search}%"
        from sqlalchemy import or_
        count_q = count_q.where(
            or_(
                Order.order_number.ilike(pattern),
                Order.customer_email.ilike(pattern),
                Order.customer_name.ilike(pattern),
            )
        )
    count_result = await db.execute(count_q)
    total = count_result.scalar_one()

    query = query.order_by(Order.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    orders = result.scalars().all()

    total_pages = (total + page_size - 1) // page_size
    return OrderListResponse(items=orders, total=total, page=page, page_size=page_size, total_pages=total_pages)


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(order_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Order)
        .options(
            selectinload(Order.line_items),
            selectinload(Order.fulfillment_allocations).selectinload(FulfillmentAllocation.node),
            selectinload(Order.shipments),
        )
        .where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Validate and repair counter mismatches
    from app.services.sourcing_engine import SourcingEngine
    import logging
    logger = logging.getLogger(__name__)
    engine = SourcingEngine(db)
    validation_result = await engine.validate_and_repair_order(order)
    if not validation_result["is_valid"]:
        logger.warning(f"Order {order_id} has counter mismatches: {validation_result['issues']}")
        if validation_result["repaired"]:
            await db.commit()
            logger.info(f"Auto-repaired counter mismatches for order {order_id}")
    
    return order


@router.get("/number/{order_number}", response_model=OrderResponse)
async def get_order_by_number(order_number: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Order)
        .options(
            selectinload(Order.line_items),
            selectinload(Order.fulfillment_allocations).selectinload(FulfillmentAllocation.node),
            selectinload(Order.shipments),
        )
        .where(Order.order_number == order_number)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.patch("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: UUID,
    payload: OrderStatusUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Order)
        .options(
            selectinload(Order.line_items),
            selectinload(Order.fulfillment_allocations).selectinload(FulfillmentAllocation.node),
            selectinload(Order.shipments),
        )
        .where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    old_status = order.status

    # Validate the transition is allowed by the order's lifecycle
    from app.services.lifecycle_engine import validate_transition
    allowed, reason = await validate_transition(db, order, payload.status.value)
    if not allowed:
        raise HTTPException(status_code=422, detail=reason)

    order.status = payload.status
    if payload.notes:
        order.notes = payload.notes

    # Set timestamps based on status
    now = datetime.utcnow()
    if payload.status == OrderStatus.CONFIRMED and not order.confirmed_at:
        order.confirmed_at = now
    elif payload.status in (OrderStatus.DELIVERED, OrderStatus.PICKED_UP):
        order.delivered_at = now
    elif payload.status == OrderStatus.CANCELLED:
        order.cancelled_at = now

    await db.flush()
    await db.refresh(order)

    background_tasks.add_task(_index_order_in_es, order)
    background_tasks.add_task(_log_order_event, str(order.id), f"order.{payload.status.value.lower()}", {
        "old_status": old_status.value,
        "new_status": payload.status.value,
        "notes": payload.notes,
    })
    background_tasks.add_task(_dispatch_webhook, str(order.id), f"order.{payload.status.value.lower()}")

    # Trigger outbound connector sync when order ships or is cancelled
    if payload.status == OrderStatus.SHIPPED and order.connector_id:
        background_tasks.add_task(_trigger_connector_sync, str(order.id))
    elif payload.status == OrderStatus.CANCELLED and order.connector_id:
        background_tasks.add_task(_trigger_connector_cancel, str(order.id))

    return order


async def _trigger_connector_sync(order_id: str):
    """Enqueue outbound fulfillment sync to the source connector."""
    try:
        from app.workers.celery_app import celery_app
        celery_app.send_task(
            "app.workers.connectors.sync_fulfillment",
            args=[order_id],
            queue="connectors",
        )
    except Exception:
        pass


async def _trigger_connector_cancel(order_id: str):
    """Enqueue outbound order cancellation to the source connector."""
    try:
        from app.workers.celery_app import celery_app
        celery_app.send_task(
            "app.workers.connectors.sync_order_cancel",
            args=[order_id],
            queue="connectors",
        )
    except Exception:
        pass


async def _dispatch_webhook(order_id: str, event_type: str):
    try:
        from app.workers.celery_app import celery_app
        celery_app.send_task(
            "app.workers.webhooks.dispatch_webhook",
            args=[order_id, event_type],
            queue="webhooks",
        )
    except Exception:
        pass


@router.post("/{order_id}/cancel", response_model=OrderResponse)
async def cancel_order(
    order_id: UUID,
    payload: CancelOrderRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Order)
        .options(
            selectinload(Order.line_items),
            selectinload(Order.fulfillment_allocations).selectinload(FulfillmentAllocation.node),
            selectinload(Order.shipments),
        )
        .where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status in (OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.CANCELLED):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel order in status: {order.status.value}"
        )

    order.status = OrderStatus.CANCELLED
    order.cancelled_at = datetime.utcnow()
    order.notes = f"Cancelled: {payload.reason}"

    await db.flush()
    await db.refresh(order)

    background_tasks.add_task(_log_order_event, str(order.id), "order.cancelled", {
        "reason": payload.reason,
        "notify_customer": payload.notify_customer,
    })
    background_tasks.add_task(_dispatch_webhook, str(order.id), "order.cancelled")

    # Customer cancellation notification
    if payload.notify_customer:
        background_tasks.add_task(_trigger_cancellation_notification, str(order.id), payload.reason)

    # Push cancellation to external connector platform
    if order.connector_id:
        background_tasks.add_task(_trigger_connector_cancel, str(order.id))

    return order


class WorkerTriggerRequest(BaseModel):
    action: Literal["source", "pick", "pack", "ship"]


@router.post("/{order_id}/trigger-worker")
async def trigger_order_worker(
    order_id: UUID,
    payload: WorkerTriggerRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Manually dispatch a Celery worker task for this order."""
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    env_id = getattr(request.state, "environment_id", "") or ""

    action_map = {
        "source": ("app.workers.sourcing.source_order",       "sourcing"),
        "pick":   ("app.workers.fulfillment.start_picking",   "fulfillment"),
        "pack":   ("app.workers.fulfillment.complete_packing", "fulfillment"),
        "ship":   ("app.workers.carrier.book_shipment",        "carrier"),
    }
    task_name, queue = action_map[payload.action]
    try:
        from app.workers.celery_app import celery_app
        celery_app.send_task(task_name, args=[str(order_id), env_id], queue=queue)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to queue task: {exc}")

    return {"action": payload.action, "order_id": str(order_id), "queued": True}


@router.get("/{order_id}/events", response_model=list)
async def get_order_events(order_id: UUID):
    """Get audit trail from MongoDB."""
    try:
        from app.database.mongodb import get_mongo_db
        db = await get_mongo_db()
        cursor = db.order_events.find(
            {"order_id": str(order_id)},
            {"_id": 0}
        ).sort("timestamp", -1).limit(100)
        events = await cursor.to_list(length=100)
        for e in events:
            if "timestamp" in e:
                e["timestamp"] = e["timestamp"].isoformat()
        return events
    except Exception as ex:
        raise HTTPException(status_code=500, detail=str(ex))
