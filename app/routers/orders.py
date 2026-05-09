"""Orders router — core order lifecycle management."""
import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload
from typing import List, Literal, Optional
from uuid import UUID
from pydantic import BaseModel
from datetime import datetime, timezone
from decimal import Decimal

from app.database.postgres import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.brand import get_accessible_brand_ids
from app.models.postgres.order_models import (
    Order, OrderItem, FulfillmentAllocation, Shipment,
    OrderStatus, PaymentStatus, OrderChannel, FulfillmentType
)
from app.schemas.orders import (
    OrderCreate, OrderUpdate, OrderResponse, OrderListResponse,
    OrderStatusUpdate, CancelOrderRequest, OrderFilterParams,
    PaymentStatusUpdate, OrderEdit,
)

# B2B models — imported lazily inside functions to tolerate model agent ordering
try:
    from app.models.postgres.b2b_models import (
        CustomerAccount, AccountType, ApprovalStatus,
    )
    _B2B_MODELS_AVAILABLE = True
except ImportError:
    _B2B_MODELS_AVAILABLE = False

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
    brand_ids: Optional[List[str]] = Depends(get_accessible_brand_ids),
):
    # Brand-scope guard: reject if the caller is restricted and the order's
    # brand_id is not in their allowed set.
    order_brand_id = str(payload.brand_id) if getattr(payload, "brand_id", None) else None
    if brand_ids is not None:
        # brand_ids == [] means no brands accessible at all
        if not brand_ids:
            raise HTTPException(
                status_code=403,
                detail="You have no brand access in this environment",
            )
        if order_brand_id and order_brand_id not in brand_ids:
            raise HTTPException(
                status_code=403,
                detail=f"You do not have access to brand {order_brand_id}",
            )

    # Calculate totals
    subtotal = sum(
        (item.unit_price * item.quantity) - item.discount_amount
        for item in payload.line_items
    )
    tax_amount = sum(item.tax_amount * item.quantity for item in payload.line_items)
    total = subtotal + tax_amount + payload.shipping_amount - payload.discount_amount

    # Resolve the lifecycle that governs this order's status transitions
    from app.services.lifecycle_engine import resolve_lifecycle
    _ot = payload.order_type.value if hasattr(payload, "order_type") and payload.order_type else None
    _bid = str(payload.brand_id) if hasattr(payload, "brand_id") and payload.brand_id else None
    lc, _ = await resolve_lifecycle(
        db,
        payload.fulfillment_type.value,
        payload.channel.value,
        pipeline_type="ORDER",
        order_type=_ot,
        brand_id=_bid,
    )

    # B2B account validation — runs only when the order carries a customer_account_id
    # and the b2b_models module is available (added by model agent).
    approval_status: Optional[str] = None
    b2b_account = None
    order_total_float = float(total)

    customer_account_id = getattr(payload, "customer_account_id", None)
    if customer_account_id and _B2B_MODELS_AVAILABLE:
        # SELECT FOR UPDATE to prevent concurrent credit over-commitment
        acct_result = await db.execute(
            select(CustomerAccount)
            .where(CustomerAccount.id == customer_account_id)
            .with_for_update()
        )
        account = acct_result.scalar_one_or_none()
        if not account:
            raise HTTPException(status_code=404, detail="Customer account not found")

        # Fix 1: ON_HOLD accounts cannot place new orders
        if account.account_type == AccountType.ON_HOLD:
            raise HTTPException(
                status_code=422,
                detail=f"Account {account.account_number} is ON_HOLD — new orders are blocked",
            )

        # Resolve approval_status from payload (B2B orders may start as PENDING)
        raw_approval_status = getattr(payload, "approval_status", None)
        if raw_approval_status is not None:
            approval_status = (
                raw_approval_status.value
                if hasattr(raw_approval_status, "value")
                else str(raw_approval_status)
            )
        else:
            # Determine automatically based on credit limit
            if (
                account.credit_limit is not None
                and float(account.credit_used or 0) + order_total_float > float(account.credit_limit)
            ):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Credit limit exceeded for account {account.account_number}: "
                        f"limit={account.credit_limit}, used={account.credit_used}, "
                        f"order={order_total_float}"
                    ),
                )
            approval_status = ApprovalStatus.PENDING.value if hasattr(ApprovalStatus, "PENDING") else None

        b2b_account = account

    # Initial order status: B2B PENDING orders wait for approval before entering CONFIRMED
    initial_order_status = (
        OrderStatus.PENDING
        if approval_status == (ApprovalStatus.PENDING.value if _B2B_MODELS_AVAILABLE and hasattr(ApprovalStatus, "PENDING") else "__never__")
        else OrderStatus.CONFIRMED
    )

    order = Order(
        order_number=_generate_order_number(),
        channel=payload.channel,
        fulfillment_type=payload.fulfillment_type,
        status=initial_order_status,
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

    # Attach B2B fields if the column exists on the model
    if customer_account_id and _B2B_MODELS_AVAILABLE:
        if hasattr(order, "customer_account_id"):
            order.customer_account_id = customer_account_id
        if hasattr(order, "approval_status") and approval_status is not None:
            order.approval_status = approval_status

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

    # Fix 2: Reserve credit only when the order is NOT waiting for approval.
    # PENDING B2B orders have not been committed yet — credit is locked at approval time.
    if b2b_account is not None and approval_status != (
        ApprovalStatus.PENDING.value if _B2B_MODELS_AVAILABLE and hasattr(ApprovalStatus, "PENDING") else "__never__"
    ):
        b2b_account.credit_used = Decimal(
            str(float(b2b_account.credit_used or 0) + order_total_float)
        )
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
    request: Request,
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
    brand_ids: Optional[List[str]] = Depends(get_accessible_brand_ids),
):
    # Brand-scoped users with no brand assignments see an empty result set
    if brand_ids is not None and not brand_ids:
        return OrderListResponse(items=[], total=0, page=page, page_size=page_size, total_pages=0)

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

    # Apply brand restriction when the caller is brand-scoped
    if brand_ids is not None:
        import uuid as _uuid
        brand_uuids = [_uuid.UUID(bid) for bid in brand_ids]
        query = query.where(Order.brand_id.in_(brand_uuids))

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
    if brand_ids is not None:
        import uuid as _uuid
        brand_uuids = [_uuid.UUID(bid) for bid in brand_ids]
        count_q = count_q.where(Order.brand_id.in_(brand_uuids))

    count_result = await db.execute(count_q)
    total = count_result.scalar_one()

    query = query.order_by(Order.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    orders = result.scalars().all()

    total_pages = (total + page_size - 1) // page_size
    return OrderListResponse(items=orders, total=total, page=page, page_size=page_size, total_pages=total_pages)


@router.patch("/{order_id}/payment-status", response_model=OrderResponse)
async def update_payment_status(
    order_id: UUID,
    payload: PaymentStatusUpdate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    brand_ids: Optional[List[str]] = Depends(get_accessible_brand_ids),
):
    """Update the payment status of an order.

    Records an audit event in MongoDB with old/new status, transaction reference,
    and the identity of the user who made the change.
    """
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

    if brand_ids is not None:
        if not brand_ids or str(order.brand_id) not in brand_ids:
            raise HTTPException(status_code=403, detail="Access denied")

    old_status = order.payment_status

    # Warn (but do not block) if a refund-type status is applied to a non-terminal order.
    # Payment processors may update payment status ahead of fulfilment status.
    refund_statuses = {PaymentStatus.REFUNDED, PaymentStatus.PARTIALLY_REFUNDED}
    terminal_order_statuses = {OrderStatus.DELIVERED, OrderStatus.SHIPPED, OrderStatus.RETURNED}
    if payload.payment_status in refund_statuses and order.status not in terminal_order_statuses:
        logger.warning(
            "Payment status %s set on order %s which is in status %s — "
            "payment system may be ahead of fulfilment status",
            payload.payment_status.value,
            order_id,
            order.status.value,
        )

    order.payment_status = payload.payment_status

    # Persist the transaction ID into metadata_ without overwriting other keys
    if payload.transaction_id is not None:
        existing_meta = order.metadata_ or {}
        order.metadata_ = {**existing_meta, "payment_transaction_id": payload.transaction_id}

    await db.flush()
    await db.refresh(order)

    background_tasks.add_task(
        _log_order_event,
        str(order.id),
        "order.payment_status_updated",
        {
            "old_status": old_status.value,
            "new_status": payload.payment_status.value,
            "transaction_id": payload.transaction_id,
            "notes": payload.notes,
            "updated_by": current_user.get("email"),
        },
    )

    return order


@router.patch("/{order_id}", response_model=OrderResponse)
async def edit_order(
    order_id: UUID,
    payload: OrderEdit,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    brand_ids: Optional[List[str]] = Depends(get_accessible_brand_ids),
):
    """Edit safe post-creation fields (address, contact info, notes) on an order.

    Blocked for orders that have already shipped, been delivered, or are in a
    terminal state. Records a snapshot of changed fields in metadata_ and an
    audit event in MongoDB.
    """
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

    if brand_ids is not None:
        if not brand_ids or str(order.brand_id) not in brand_ids:
            raise HTTPException(status_code=403, detail="Access denied")

    non_editable_statuses = {
        OrderStatus.SHIPPED,
        OrderStatus.DELIVERED,
        OrderStatus.CANCELLED,
        OrderStatus.RETURNED,
        OrderStatus.REFUNDED,
    }
    if order.status in non_editable_statuses:
        raise HTTPException(
            status_code=422,
            detail=f"Order cannot be edited in {order.status.value} status",
        )

    # Build the map of ORM attribute names to new values for non-None payload fields
    field_map = {
        "customer_name":      payload.customer_name,
        "customer_email":     str(payload.customer_email) if payload.customer_email is not None else None,
        "customer_phone":     payload.customer_phone,
        "shipping_address1":  payload.shipping_address1,
        "shipping_address2":  payload.shipping_address2,
        "shipping_city":      payload.shipping_city,
        "shipping_state":     payload.shipping_state,
        "shipping_postal_code": payload.shipping_postal_code,
        "shipping_country":   payload.shipping_country,
        "shipping_name":      payload.shipping_name,
        "notes":              payload.notes,
    }

    changed_fields: list[str] = []
    for attr, new_value in field_map.items():
        if new_value is not None:
            setattr(order, attr, new_value)
            changed_fields.append(attr)

    if not changed_fields:
        # Nothing changed — return current state without a DB round-trip
        return order

    # Record edit snapshot in metadata_
    existing_meta = order.metadata_ or {}
    order.metadata_ = {
        **existing_meta,
        "last_edit": {
            "changed_fields": changed_fields,
            "edited_by": current_user.get("email"),
            "edited_at": datetime.utcnow().isoformat(),
        },
    }

    await db.flush()
    await db.refresh(order)

    background_tasks.add_task(_index_order_in_es, order)
    background_tasks.add_task(
        _log_order_event,
        str(order.id),
        "order.edited",
        {
            "changed_fields": changed_fields,
            "edited_by": current_user.get("email"),
        },
    )

    return order


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    brand_ids: Optional[List[str]] = Depends(get_accessible_brand_ids),
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

    if brand_ids is not None:
        if not brand_ids or str(order.brand_id) not in brand_ids:
            raise HTTPException(status_code=403, detail="Access denied")

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
    request: Request,
    db: AsyncSession = Depends(get_db),
    brand_ids: Optional[List[str]] = Depends(get_accessible_brand_ids),
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

    if brand_ids is not None:
        if not brand_ids or str(order.brand_id) not in brand_ids:
            raise HTTPException(status_code=403, detail="Access denied")

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
    request: Request,
    db: AsyncSession = Depends(get_db),
    brand_ids: Optional[List[str]] = Depends(get_accessible_brand_ids),
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

    if brand_ids is not None:
        if not brand_ids or str(order.brand_id) not in brand_ids:
            raise HTTPException(status_code=403, detail="Access denied")

    if order.status in (OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.CANCELLED):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel order in status: {order.status.value}"
        )

    order.status = OrderStatus.CANCELLED
    order.cancelled_at = datetime.now(tz=timezone.utc)
    order.notes = f"Cancelled: {payload.reason}"

    # Fix 2 (cancel side): only release credit_used when the order was APPROVED
    # (i.e. credit was actually reserved). PENDING/REJECTED orders never had credit locked.
    if (
        _B2B_MODELS_AVAILABLE
        and hasattr(order, "customer_account_id")
        and order.customer_account_id is not None
        and hasattr(order, "approval_status")
        and order.approval_status == ApprovalStatus.APPROVED.value
    ):
        acct_result = await db.execute(
            select(CustomerAccount)
            .where(CustomerAccount.id == order.customer_account_id)
            .with_for_update()
        )
        cancel_account = acct_result.scalar_one_or_none()
        if cancel_account is not None:
            released = float(order.total_amount or 0)
            new_used = max(0.0, float(cancel_account.credit_used or 0) - released)
            cancel_account.credit_used = Decimal(str(new_used))

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


class ApproveOrderRequest(BaseModel):
    approved: bool
    notes: Optional[str] = None


@router.post("/{order_id}/approve", response_model=OrderResponse)
async def approve_order(
    order_id: UUID,
    payload: ApproveOrderRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
    brand_ids: Optional[List[str]] = Depends(get_accessible_brand_ids),
):
    """Approve or reject a B2B order that is awaiting approval.

    Approval: PENDING → CONFIRMED with credit reserved.
    Rejection: PENDING → CANCELLED (terminal), credit untouched, audit event logged.
    """
    if not _B2B_MODELS_AVAILABLE:
        raise HTTPException(status_code=501, detail="B2B module not available")

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

    if brand_ids is not None:
        if not brand_ids or str(order.brand_id) not in brand_ids:
            raise HTTPException(status_code=403, detail="Access denied")

    # Guard: only PENDING approval orders can be approved/rejected
    current_approval = getattr(order, "approval_status", None)
    pending_val = ApprovalStatus.PENDING.value if hasattr(ApprovalStatus, "PENDING") else None
    if current_approval != pending_val:
        raise HTTPException(
            status_code=422,
            detail=f"Order approval_status is '{current_approval}', expected PENDING",
        )

    env_id = getattr(request.state, "environment_id", "") or ""

    if payload.approved:
        # Fix 2 (approve side): reserve credit now that the order is committed
        if hasattr(order, "customer_account_id") and order.customer_account_id is not None:
            acct_result = await db.execute(
                select(CustomerAccount)
                .where(CustomerAccount.id == order.customer_account_id)
                .with_for_update()
            )
            account = acct_result.scalar_one_or_none()
            if account is not None and account.credit_limit is not None:
                order_total = float(order.total_amount or 0)
                current_used = float(account.credit_used or 0)
                if current_used + order_total > float(account.credit_limit):
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"Credit limit would be exceeded on approval for account "
                            f"{account.account_number}: limit={account.credit_limit}, "
                            f"used={account.credit_used}, order={order_total}"
                        ),
                    )
                account.credit_used = Decimal(str(current_used + order_total))

        # Transition to CONFIRMED
        if hasattr(order, "approval_status"):
            order.approval_status = ApprovalStatus.APPROVED.value
        order.status = OrderStatus.CONFIRMED
        order.confirmed_at = datetime.now(tz=timezone.utc)
        if payload.notes:
            order.notes = payload.notes

        await db.flush()
        await db.refresh(order)

        background_tasks.add_task(_index_order_in_es, order)
        background_tasks.add_task(_log_order_event, str(order.id), "order.approved", {
            "order_number": order.order_number,
            "approved_by": "api",
            "notes": payload.notes,
        })
        background_tasks.add_task(_trigger_sourcing, str(order.id), env_id)

    else:
        # Fix 3: Rejection — terminal state, no credit reserved
        if hasattr(order, "approval_status"):
            order.approval_status = ApprovalStatus.REJECTED.value
        # OrderStatus has no REJECTED value — use CANCELLED as the terminal state
        order.status = OrderStatus.CANCELLED
        order.cancelled_at = datetime.now(tz=timezone.utc)
        if payload.notes:
            order.notes = payload.notes

        await db.flush()
        await db.refresh(order)

        background_tasks.add_task(_index_order_in_es, order)
        background_tasks.add_task(_log_order_event, str(order.id), "order.rejected", {
            "order_number": order.order_number,
            "reason": payload.notes or "Rejected by approver",
        })
        background_tasks.add_task(_dispatch_webhook, str(order.id), "order.rejected")

    return order


class WorkerTriggerRequest(BaseModel):
    action: Literal["source", "pick", "pack", "ship"]


@router.post("/{order_id}/trigger-worker")
async def trigger_order_worker(
    order_id: UUID,
    payload: WorkerTriggerRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    brand_ids: Optional[List[str]] = Depends(get_accessible_brand_ids),
):
    """Manually dispatch a Celery worker task for this order."""
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if brand_ids is not None:
        if not brand_ids or str(order.brand_id) not in brand_ids:
            raise HTTPException(status_code=403, detail="Access denied")

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
