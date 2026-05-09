"""Inventory router — real-time stock management."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from typing import Optional, List
from uuid import UUID

from app.database.postgres import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.brand import get_accessible_brand_ids
from app.models.postgres.brand_models import Brand, InventoryMode
from app.models.postgres.inventory_models import (
    InventoryItem, InventoryAdjustment, InventoryReservation
)
from app.models.postgres.node_models import FulfillmentNode
from app.schemas.inventory import (
    InventoryItemCreate, InventoryItemUpdate, InventoryItemResponse,
    InventoryAdjustmentCreate, InventoryAdjustmentResponse,
    BulkInventoryCheck, InventoryCheckResult, InventoryTransfer,
    ProductSummary, ProductUpdate,
)

router = APIRouter(prefix="/inventory", tags=["Inventory"], dependencies=[Depends(get_current_user)])


@router.post("/", response_model=InventoryItemResponse, status_code=201)
async def create_inventory_item(payload: InventoryItemCreate, db: AsyncSession = Depends(get_db)):
    # Verify node exists
    node = await db.get(FulfillmentNode, payload.node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    # Check uniqueness
    result = await db.execute(
        select(InventoryItem).where(
            and_(InventoryItem.node_id == payload.node_id, InventoryItem.sku == payload.sku)
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Inventory item already exists for this node/SKU")

    item = InventoryItem(
        **payload.model_dump(),
        quantity_available=payload.quantity_on_hand,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return item


@router.get("/", response_model=List[InventoryItemResponse])
async def list_inventory(
    request: Request,
    node_id: Optional[UUID] = None,
    sku: Optional[str] = None,
    brand_id: Optional[str] = Query(default=None),
    low_stock_only: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    accessible_brand_ids: Optional[List[str]] = Depends(get_accessible_brand_ids),
):
    """List inventory items.

    Brand-scope rules (applied in this order):
    1. Brand-scoped users (non-superadmin with UserBrandRole assignments) only see
       inventory belonging to their accessible brands. An empty assignment set returns
       no results.
    2. When brand_id query param is provided for a brand using ISOLATED inventory mode,
       results are additionally filtered to stock owned by that brand.
    3. SHARED mode brands (or when brand_id is omitted) apply no extra brand filter
       beyond the scope restriction from rule 1.
    """
    # Return empty list immediately when caller has no brand access
    if accessible_brand_ids is not None and not accessible_brand_ids:
        return []

    query = select(InventoryItem).where(InventoryItem.is_active == True)
    if node_id:
        query = query.where(InventoryItem.node_id == node_id)
    if sku:
        query = query.where(InventoryItem.sku == sku)
    if low_stock_only:
        query = query.where(InventoryItem.quantity_available <= InventoryItem.reorder_point)

    # Apply user brand-scope restriction
    if accessible_brand_ids is not None:
        brand_uuids = [UUID(bid) for bid in accessible_brand_ids]
        query = query.where(InventoryItem.brand_id.in_(brand_uuids))

    # Brand-scoped filtering for ISOLATED inventory mode (explicit brand_id param)
    if brand_id:
        try:
            brand_uuid = UUID(brand_id)
            brand = await db.get(Brand, brand_uuid)
            if brand and brand.inventory_mode == InventoryMode.ISOLATED.value:
                query = query.where(InventoryItem.brand_id == brand_uuid)
            # SHARED mode: return all inventory (no additional filter)
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail="Invalid brand_id format")

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/sku/{sku}", response_model=List[InventoryItemResponse])
async def get_inventory_by_sku(sku: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(InventoryItem).where(InventoryItem.sku == sku, InventoryItem.is_active == True)
    )
    items = result.scalars().all()
    if not items:
        raise HTTPException(status_code=404, detail=f"No inventory found for SKU: {sku}")
    return items


@router.get("/products", response_model=List[ProductSummary])
async def list_products(
    search: Optional[str] = None,
    node_id: Optional[UUID] = None,
    low_stock_only: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Return all distinct SKUs with aggregated stock totals across all nodes."""
    query = (
        select(
            InventoryItem.sku,
            func.max(InventoryItem.product_name).label("product_name"),
            func.sum(InventoryItem.quantity_on_hand).label("total_on_hand"),
            func.sum(InventoryItem.quantity_available).label("total_available"),
            func.sum(InventoryItem.quantity_reserved).label("total_reserved"),
            func.count(InventoryItem.id).label("nodes_count"),
            func.max(InventoryItem.unit_cost).label("unit_cost"),
            func.max(InventoryItem.weight_lbs).label("weight_lbs"),
            func.max(InventoryItem.reorder_point).label("reorder_point"),
            func.max(InventoryItem.updated_at).label("updated_at"),
        )
        .where(InventoryItem.is_active == True)
        .group_by(InventoryItem.sku)
        .order_by(InventoryItem.sku)
    )
    if node_id:
        query = query.where(InventoryItem.node_id == node_id)
    if search:
        query = query.where(
            or_(
                InventoryItem.sku.ilike(f"%{search}%"),
                InventoryItem.product_name.ilike(f"%{search}%"),
            )
        )
    if low_stock_only:
        query = query.having(
            func.sum(InventoryItem.quantity_available) <= func.max(InventoryItem.reorder_point)
        )
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    rows = result.all()
    return [
        ProductSummary(
            sku=row.sku,
            product_name=row.product_name,
            total_on_hand=row.total_on_hand or 0,
            total_available=row.total_available or 0,
            total_reserved=row.total_reserved or 0,
            nodes_count=row.nodes_count or 0,
            unit_cost=row.unit_cost or 0.0,
            weight_lbs=row.weight_lbs or 0.0,
            reorder_point=row.reorder_point or 0,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.patch("/products/{sku}", response_model=dict)
async def update_product(
    sku: str,
    payload: ProductUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    brand_ids: Optional[List[str]] = Depends(get_accessible_brand_ids),
):
    """Update product-level attributes for all inventory items with this SKU."""
    result = await db.execute(
        select(InventoryItem).where(InventoryItem.sku == sku, InventoryItem.is_active == True)
    )
    items = result.scalars().all()
    if not items:
        raise HTTPException(status_code=404, detail=f"No inventory found for SKU: {sku}")

    # Brand-scope filtering: restrict to items the caller can access.
    # Superadmin (brand_ids is None) updates all items as before.
    if brand_ids is not None:
        items = [item for item in items if str(item.brand_id) in brand_ids]

    update_data = payload.model_dump(exclude_unset=True)
    for item in items:
        for field, value in update_data.items():
            setattr(item, field, value)
    await db.flush()
    return {"updated": len(items), "sku": sku}


@router.get("/{item_id}", response_model=InventoryItemResponse)
async def get_inventory_item(
    item_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    brand_ids: Optional[List[str]] = Depends(get_accessible_brand_ids),
):
    item = await db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    if brand_ids is not None:
        if not brand_ids or str(item.brand_id) not in brand_ids:
            raise HTTPException(status_code=403, detail="Access denied")

    return item


@router.patch("/{item_id}", response_model=InventoryItemResponse)
async def update_inventory_item(
    item_id: UUID,
    payload: InventoryItemUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    brand_ids: Optional[List[str]] = Depends(get_accessible_brand_ids),
):
    item = await db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    if brand_ids is not None:
        if not brand_ids or str(item.brand_id) not in brand_ids:
            raise HTTPException(status_code=403, detail="Access denied")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await db.flush()
    await db.refresh(item)
    return item


@router.post("/{item_id}/adjust", response_model=InventoryAdjustmentResponse)
async def adjust_inventory(
    item_id: UUID,
    payload: InventoryAdjustmentCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
    brand_ids: Optional[List[str]] = Depends(get_accessible_brand_ids),
):
    item = await db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    if brand_ids is not None:
        if not brand_ids or str(item.brand_id) not in brand_ids:
            raise HTTPException(status_code=403, detail="Access denied")

    quantity_before = item.quantity_on_hand
    quantity_after = max(0, quantity_before + payload.quantity_delta)

    # Update inventory
    item.quantity_on_hand = quantity_after
    item.quantity_available = max(0, quantity_after - item.quantity_reserved)

    adj = InventoryAdjustment(
        inventory_item_id=item_id,
        reason=payload.reason,
        quantity_delta=payload.quantity_delta,
        quantity_before=quantity_before,
        quantity_after=quantity_after,
        reference_id=payload.reference_id,
        notes=payload.notes,
        created_by=payload.created_by,
    )
    db.add(adj)
    await db.flush()
    await db.refresh(adj)

    # Push updated quantity to connected platforms (fire-and-forget)
    background_tasks.add_task(
        _trigger_inventory_sync, str(item_id), int(item.quantity_available)
    )

    return adj


async def _trigger_inventory_sync(inventory_item_id: str, quantity_available: int) -> None:
    """Enqueue outbound inventory push to all connected platforms."""
    try:
        from app.workers.celery_app import celery_app
        celery_app.send_task(
            "app.workers.inventory_sync.push_inventory_to_connectors",
            args=[inventory_item_id, quantity_available],
            queue="connectors",
        )
    except Exception:
        pass


@router.post("/check-availability", response_model=List[InventoryCheckResult])
async def check_availability(payload: BulkInventoryCheck, db: AsyncSession = Depends(get_db)):
    results = []
    for item_req in payload.items:
        sku = item_req.get("sku")
        qty_needed = item_req.get("quantity", 1)

        result = await db.execute(
            select(InventoryItem, FulfillmentNode).join(
                FulfillmentNode, InventoryItem.node_id == FulfillmentNode.id
            ).where(
                InventoryItem.sku == sku,
                InventoryItem.is_active == True,
                InventoryItem.quantity_available > 0,
                FulfillmentNode.status == "ACTIVE",
            ).order_by(InventoryItem.quantity_available.desc())
        )
        rows = result.all()

        available_by_node = [
            {
                "node_id": str(inv.id),
                "node_code": node.code,
                "node_name": node.name,
                "quantity_available": inv.quantity_available,
            }
            for inv, node in rows
        ]
        total_available = sum(r["quantity_available"] for r in available_by_node)

        results.append(InventoryCheckResult(
            sku=sku,
            requested_quantity=qty_needed,
            available_by_node=available_by_node,
            total_available=total_available,
            fulfillable=total_available >= qty_needed,
        ))
    return results


@router.post("/transfer", response_model=dict)
async def transfer_inventory(
    payload: InventoryTransfer,
    request: Request,
    db: AsyncSession = Depends(get_db),
    brand_ids: Optional[List[str]] = Depends(get_accessible_brand_ids),
):
    """Transfer inventory between nodes."""
    from app.models.postgres.inventory_models import InventoryAdjustmentReason

    # Get source item
    result = await db.execute(
        select(InventoryItem).where(
            InventoryItem.node_id == payload.from_node_id,
            InventoryItem.sku == payload.sku,
        )
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source inventory item not found")

    if brand_ids is not None:
        if not brand_ids or str(source.brand_id) not in brand_ids:
            raise HTTPException(status_code=403, detail="Access denied")

    if source.quantity_available < payload.quantity:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient quantity. Available: {source.quantity_available}"
        )

    # Get or create destination item
    result = await db.execute(
        select(InventoryItem).where(
            InventoryItem.node_id == payload.to_node_id,
            InventoryItem.sku == payload.sku,
        )
    )
    dest = result.scalar_one_or_none()
    if not dest:
        dest = InventoryItem(
            node_id=payload.to_node_id,
            sku=payload.sku,
            product_name=source.product_name,
            quantity_on_hand=0,
            quantity_available=0,
        )
        db.add(dest)
        await db.flush()

    transfer_ref = f"TRANSFER-{payload.from_node_id}-{payload.to_node_id}"

    # Deduct from source
    source_before = source.quantity_on_hand
    source.quantity_on_hand -= payload.quantity
    source.quantity_available = max(0, source.quantity_on_hand - source.quantity_reserved)
    db.add(InventoryAdjustment(
        inventory_item_id=source.id,
        reason=InventoryAdjustmentReason.TRANSFER_OUT,
        quantity_delta=-payload.quantity,
        quantity_before=source_before,
        quantity_after=source.quantity_on_hand,
        reference_id=transfer_ref,
        notes=payload.notes,
    ))

    # Add to destination
    dest_before = dest.quantity_on_hand
    dest.quantity_on_hand += payload.quantity
    dest.quantity_available = max(0, dest.quantity_on_hand - dest.quantity_reserved)
    db.add(InventoryAdjustment(
        inventory_item_id=dest.id,
        reason=InventoryAdjustmentReason.TRANSFER_IN,
        quantity_delta=payload.quantity,
        quantity_before=dest_before,
        quantity_after=dest.quantity_on_hand,
        reference_id=transfer_ref,
        notes=payload.notes,
    ))

    await db.flush()
    return {"message": "Transfer completed", "reference": transfer_ref}
