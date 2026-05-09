"""Returns router — RMA workflow and refund recording."""
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.postgres import get_db
from app.dependencies.auth import get_current_user, require_superadmin
from app.models.postgres.order_models import Order
from app.models.postgres.return_models import (
    OrderReturn,
    RefundStatus,
    Refund,
    ReturnItem,
    ReturnStatus,
)
from app.schemas.returns import (
    RefundCreate,
    RefundResponse,
    ReturnCreate,
    ReturnListResponse,
    ReturnResponse,
    ReturnUpdate,
)

router = APIRouter(
    prefix="/returns",
    tags=["Returns"],
)

# Standalone order-level refund sub-router (mounted at /orders/{order_id}/refunds)
order_refunds_router = APIRouter(tags=["Returns"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_rma_number() -> str:
    month_str = datetime.now(tz=timezone.utc).strftime("%Y%m")
    suffix = secrets.token_hex(3).upper()  # 6 hex chars
    return f"RMA-{month_str}-{suffix}"


def _generate_refund_number() -> str:
    month_str = datetime.now(tz=timezone.utc).strftime("%Y%m")
    suffix = secrets.token_hex(3).upper()  # 6 hex chars
    return f"REF-{month_str}-{suffix}"


async def _log_order_event(order_id: str, event_type: str, data: dict):
    """Append event to MongoDB audit trail (mirrors orders router helper)."""
    try:
        from app.database.mongodb import get_mongo_db
        mdb = await get_mongo_db()
        await mdb.order_events.insert_one({
            "order_id": order_id,
            "event_type": event_type,
            "timestamp": datetime.utcnow(),
            "data": data,
        })
    except Exception:
        pass  # Non-blocking; audit failure must not break the API response


async def _load_return(db: AsyncSession, return_id: UUID) -> OrderReturn:
    """Load OrderReturn with items and refund eagerly loaded."""
    result = await db.execute(
        select(OrderReturn)
        .options(
            selectinload(OrderReturn.items),
            selectinload(OrderReturn.refund),
        )
        .where(OrderReturn.id == return_id)
    )
    order_return = result.scalar_one_or_none()
    if not order_return:
        raise HTTPException(status_code=404, detail="Return not found")
    return order_return


def _return_response(order_return: OrderReturn) -> ReturnResponse:
    """Build a ReturnResponse from an ORM object."""
    refund_resp = None
    if order_return.refund:
        refund_resp = RefundResponse.model_validate(order_return.refund)
    items = [
        _item_response_dict(item)
        for item in (order_return.items or [])
    ]
    data = {
        "id": order_return.id,
        "return_number": order_return.return_number,
        "order_id": order_return.order_id,
        "status": order_return.status,
        "reason": order_return.reason,
        "customer_notes": order_return.customer_notes,
        "staff_notes": order_return.staff_notes,
        "return_tracking_number": order_return.return_tracking_number,
        "return_carrier": order_return.return_carrier,
        "received_at": order_return.received_at,
        "restocked_at": order_return.restocked_at,
        "created_at": order_return.created_at,
        "updated_at": order_return.updated_at,
        "items": items,
        "refund": refund_resp,
    }
    return ReturnResponse.model_validate(data)


def _item_response_dict(item: ReturnItem) -> dict:
    return {
        "id": item.id,
        "return_id": item.return_id,
        "order_item_id": item.order_item_id,
        "sku": item.sku,
        "description": item.description,
        "quantity_requested": item.quantity_requested,
        "quantity_received": item.quantity_received,
        "condition": item.condition,
        "restock": item.restock,
        "created_at": item.created_at,
    }


async def _restock_return_items(
    db: AsyncSession, order_return: OrderReturn
) -> list[tuple[str, int]]:
    """
    For each ReturnItem with restock=True, create an InventoryAdjustment and
    increment inventory_on_hand at the node that fulfilled the original order.

    Returns a list of (inventory_item_id, quantity_available) tuples for each
    item that was restocked, so callers can fire connector sync tasks.
    """
    from app.models.postgres.inventory_models import (
        InventoryItem,
        InventoryAdjustment,
        InventoryAdjustmentReason,
    )

    # Determine the primary node for the order via fulfillment allocations
    from app.models.postgres.order_models import FulfillmentAllocation
    alloc_result = await db.execute(
        select(FulfillmentAllocation.node_id)
        .where(FulfillmentAllocation.order_id == order_return.order_id)
        .limit(1)
    )
    node_id_row = alloc_result.first()
    node_id = node_id_row[0] if node_id_row else None

    restocked: list[tuple[str, int]] = []

    for item in order_return.items or []:
        if not item.restock:
            continue
        qty = float(item.quantity_received or item.quantity_requested)
        if qty <= 0:
            continue

        # Try to find inventory record; skip gracefully if not found
        inv_stmt = select(InventoryItem).where(InventoryItem.sku == item.sku)
        if node_id:
            inv_stmt = inv_stmt.where(InventoryItem.node_id == node_id)
        inv_result = await db.execute(inv_stmt.limit(1))
        inv_item = inv_result.scalar_one_or_none()

        if not inv_item:
            continue

        before = inv_item.quantity_on_hand
        delta = int(round(qty))
        inv_item.quantity_on_hand = before + delta
        inv_item.quantity_available = inv_item.quantity_on_hand - (inv_item.quantity_reserved or 0)

        adjustment = InventoryAdjustment(
            inventory_item_id=inv_item.id,
            reason=InventoryAdjustmentReason.RETURNED,
            quantity_delta=delta,
            quantity_before=before,
            quantity_after=inv_item.quantity_on_hand,
            notes=f"Restocked via RMA {order_return.return_number}",
        )
        db.add(adjustment)
        restocked.append((str(inv_item.id), inv_item.quantity_available))

    return restocked


# ---------------------------------------------------------------------------
# RMA endpoints
# ---------------------------------------------------------------------------

@router.post("/", response_model=ReturnResponse, status_code=201, dependencies=[Depends(get_current_user)])
async def create_return(
    payload: ReturnCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new return request (RMA). Validates that the order exists."""
    from app.models.postgres.order_models import OrderStatus
    order = await db.get(Order, payload.order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status in (OrderStatus.CANCELLED, OrderStatus.PENDING):
        raise HTTPException(
            status_code=400,
            detail=f"Returns cannot be created for orders in {order.status.value} status",
        )

    # Generate unique RMA number (collision-safe)
    rma_number = None
    for _ in range(5):
        candidate = _generate_rma_number()
        clash = await db.execute(
            select(OrderReturn).where(OrderReturn.return_number == candidate)
        )
        if not clash.scalar_one_or_none():
            rma_number = candidate
            break
    if not rma_number:
        raise HTTPException(status_code=500, detail="Could not generate unique RMA number")

    order_return = OrderReturn(
        return_number=rma_number,
        order_id=payload.order_id,
        status=ReturnStatus.REQUESTED,
        reason=payload.reason,
        customer_notes=payload.customer_notes,
    )
    db.add(order_return)
    await db.flush()  # Populate order_return.id before inserting items

    for item_payload in payload.items:
        item = ReturnItem(
            return_id=order_return.id,
            order_item_id=item_payload.order_item_id,
            sku=item_payload.sku,
            description=item_payload.description,
            quantity_requested=item_payload.quantity_requested,
            restock=item_payload.restock,
        )
        db.add(item)

    await db.flush()

    # Audit event
    await _log_order_event(
        str(payload.order_id),
        "order.return_requested",
        {
            "return_id": str(order_return.id),
            "return_number": rma_number,
            "reason": payload.reason.value,
            "item_count": len(payload.items),
        },
    )

    # Reload with relationships
    reloaded = await _load_return(db, order_return.id)
    return _return_response(reloaded)


@router.get("/", response_model=ReturnListResponse)
async def list_returns(
    status: Optional[ReturnStatus] = Query(default=None),
    order_id: Optional[UUID] = Query(default=None),
    from_date: Optional[datetime] = Query(default=None),
    to_date: Optional[datetime] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """List returns with optional filters."""
    stmt = select(OrderReturn)
    if status:
        stmt = stmt.where(OrderReturn.status == status)
    if order_id:
        stmt = stmt.where(OrderReturn.order_id == order_id)
    if from_date:
        stmt = stmt.where(OrderReturn.created_at >= from_date)
    if to_date:
        stmt = stmt.where(OrderReturn.created_at <= to_date)

    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()

    stmt = (
        stmt
        .options(selectinload(OrderReturn.items), selectinload(OrderReturn.refund))
        .order_by(OrderReturn.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    returns = (await db.execute(stmt)).scalars().all()

    return ReturnListResponse(
        items=[_return_response(r) for r in returns],
        total=total,
    )


@router.get("/{return_id}", response_model=ReturnResponse)
async def get_return(
    return_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Get a single return with items and refund detail."""
    order_return = await _load_return(db, return_id)
    return _return_response(order_return)


@router.patch("/{return_id}/status", response_model=ReturnResponse, dependencies=[Depends(require_superadmin)])
async def update_return_status(
    return_id: UUID,
    payload: ReturnUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Update return status.

    - RECEIVED: sets received_at timestamp.
    - RESTOCKED: sets restocked_at; creates inventory RETURNED adjustments
      for all items with restock=True.
    """
    order_return = await _load_return(db, return_id)

    order_return.status = payload.status
    if payload.staff_notes is not None:
        order_return.staff_notes = payload.staff_notes
    if payload.return_tracking_number is not None:
        order_return.return_tracking_number = payload.return_tracking_number
    if payload.return_carrier is not None:
        order_return.return_carrier = payload.return_carrier

    now = datetime.now(tz=timezone.utc)

    if payload.status == ReturnStatus.RECEIVED and not order_return.received_at:
        order_return.received_at = now

    restocked_skus: list[tuple[str, int]] = []  # (inventory_item_id, qty_available)
    if payload.status == ReturnStatus.RESTOCKED:
        if order_return.restocked_at is not None:
            raise HTTPException(status_code=400, detail="Return has already been restocked")
        order_return.restocked_at = now
        restocked_skus = await _restock_return_items(db, order_return)

    await db.flush()

    # Fire connector inventory sync for each restocked item (after flush so IDs are stable)
    if restocked_skus:
        from app.workers.inventory_sync import push_inventory_to_connectors
        for inv_item_id, qty_avail in restocked_skus:
            push_inventory_to_connectors.delay(inv_item_id, qty_avail)

    # Audit event
    await _log_order_event(
        str(order_return.order_id),
        f"order.return_{payload.status.value.lower()}",
        {
            "return_id": str(order_return.id),
            "return_number": order_return.return_number,
            "new_status": payload.status.value,
        },
    )

    reloaded = await _load_return(db, return_id)
    return _return_response(reloaded)


@router.post("/{return_id}/refund", response_model=RefundResponse, status_code=201, dependencies=[Depends(get_current_user)])
async def create_refund_for_return(
    return_id: UUID,
    payload: RefundCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a refund tied to an existing return.
    Validates that amount does not exceed the original order total.
    """
    order_return = await _load_return(db, return_id)

    # Ensure a refund does not already exist for this return
    if order_return.refund:
        raise HTTPException(
            status_code=400,
            detail="A refund already exists for this return. Use the existing refund record.",
        )

    # Validate amount vs remaining refundable balance (cumulative check)
    order = await db.get(Order, order_return.order_id)
    if order and order.total_amount is not None:
        existing_sum_row = await db.execute(
            select(func.coalesce(func.sum(Refund.amount), 0))
            .where(Refund.order_id == order_return.order_id)
            .where(Refund.status != RefundStatus.FAILED)
        )
        existing_total = Decimal(str(existing_sum_row.scalar_one()))
        if existing_total + payload.amount > Decimal(str(order.total_amount)):
            raise HTTPException(
                status_code=400,
                detail=f"Refund would exceed order total. Already refunded: {existing_total}, order total: {order.total_amount}.",
            )

    refund_number = None
    for _ in range(5):
        candidate = _generate_refund_number()
        clash = await db.execute(select(Refund).where(Refund.refund_number == candidate))
        if not clash.scalar_one_or_none():
            refund_number = candidate
            break
    if not refund_number:
        raise HTTPException(status_code=500, detail="Could not generate unique refund number")

    refund = Refund(
        refund_number=refund_number,
        order_id=order_return.order_id,
        return_id=return_id,
        status=RefundStatus.PENDING,
        refund_method=payload.refund_method,
        amount=payload.amount,
        currency=payload.currency,
        transaction_id=payload.transaction_id,
        reason=payload.reason,
        notes=payload.notes,
    )
    db.add(refund)
    await db.flush()

    await _log_order_event(
        str(order_return.order_id),
        "order.refunded",
        {
            "refund_id": str(refund.id),
            "refund_number": refund_number,
            "return_id": str(return_id),
            "amount": float(payload.amount),
            "currency": payload.currency,
            "method": payload.refund_method.value,
        },
    )

    await db.refresh(refund)
    return RefundResponse.model_validate(refund)


@router.get("/{return_id}/refund", response_model=RefundResponse)
async def get_refund_for_return(
    return_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Get the refund associated with a return."""
    result = await db.execute(
        select(Refund).where(Refund.return_id == return_id)
    )
    refund = result.scalar_one_or_none()
    if not refund:
        raise HTTPException(status_code=404, detail="No refund found for this return")
    return RefundResponse.model_validate(refund)


# ---------------------------------------------------------------------------
# Order-level standalone refund endpoints
# Mounted as: /orders/{order_id}/refunds
# ---------------------------------------------------------------------------

@order_refunds_router.post(
    "/orders/{order_id}/refunds",
    response_model=RefundResponse,
    status_code=201,
    tags=["Returns"],
    dependencies=[Depends(get_current_user)],
)
async def create_order_refund(
    order_id: UUID,
    payload: RefundCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a standalone (courtesy) refund directly on an order — no return required.
    Validates that amount does not exceed the original order total.
    """
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.total_amount is not None:
        existing_sum_row = await db.execute(
            select(func.coalesce(func.sum(Refund.amount), 0))
            .where(Refund.order_id == order_id)
            .where(Refund.status != RefundStatus.FAILED)
        )
        existing_total = Decimal(str(existing_sum_row.scalar_one()))
        if existing_total + payload.amount > Decimal(str(order.total_amount)):
            raise HTTPException(
                status_code=400,
                detail=f"Refund would exceed order total. Already refunded: {existing_total}, order total: {order.total_amount}.",
            )

    refund_number = None
    for _ in range(5):
        candidate = _generate_refund_number()
        clash = await db.execute(select(Refund).where(Refund.refund_number == candidate))
        if not clash.scalar_one_or_none():
            refund_number = candidate
            break
    if not refund_number:
        raise HTTPException(status_code=500, detail="Could not generate unique refund number")

    refund = Refund(
        refund_number=refund_number,
        order_id=order_id,
        return_id=None,  # Courtesy refund — no return
        status=RefundStatus.PENDING,
        refund_method=payload.refund_method,
        amount=payload.amount,
        currency=payload.currency,
        transaction_id=payload.transaction_id,
        reason=payload.reason,
        notes=payload.notes,
    )
    db.add(refund)
    await db.flush()

    await _log_order_event(
        str(order_id),
        "order.refunded",
        {
            "refund_id": str(refund.id),
            "refund_number": refund_number,
            "return_id": None,
            "amount": float(payload.amount),
            "currency": payload.currency,
            "method": payload.refund_method.value,
            "courtesy": True,
        },
    )

    await db.refresh(refund)
    return RefundResponse.model_validate(refund)


@order_refunds_router.get(
    "/orders/{order_id}/refunds",
    response_model=List[RefundResponse],
    tags=["Returns"],
)
async def list_order_refunds(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """List all refunds recorded against an order."""
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    result = await db.execute(
        select(Refund)
        .where(Refund.order_id == order_id)
        .order_by(Refund.created_at.asc())
    )
    refunds = result.scalars().all()
    return [RefundResponse.model_validate(r) for r in refunds]
