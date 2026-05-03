"""Status rollup helpers — compute order line and order statuses from shipment data."""
from typing import List, Dict, Any, NamedTuple
from collections import defaultdict


class OrderLineQuantityBreakdown(NamedTuple):
    """Breakdown of quantities by status for an order line"""
    status: str
    quantity_pending: int
    quantity_allocated: int
    quantity_backordered: int
    quantity_shipped: int
    quantity_delivered: int


def compute_order_line_status_from_shipments(
    order_line_id: str,
    order_line_sku: str,
    order_line_quantity: int,
    allocations: List[Any],  # FulfillmentAllocation objects
    shipments: List[Any],  # Shipment objects
) -> OrderLineQuantityBreakdown:
    """
    Compute order line status and quantity breakdown based on allocations and shipments.
    
    Returns:
        OrderLineQuantityBreakdown with status and quantities for each state
    """
    from app.models.postgres.order_models import OrderItemStatus, ShipmentStatus
    
    # Only get allocations for this specific SKU
    sku_allocations = [a for a in allocations if a.sku == order_line_sku]
    
    # Calculate total allocated for this SKU
    total_allocated = sum(a.quantity_allocated for a in sku_allocations)
    
    # Track quantities by shipment status
    qty_by_status = {
        'LABEL_CREATED': 0,
        'PICKED_UP': 0,
        'IN_TRANSIT': 0,
        'OUT_FOR_DELIVERY': 0,
        'DELIVERED': 0,
    }
    
    # Track which allocations have been counted (to avoid double-counting)
    counted_allocation_ids = set()
    
    # Build a lookup: allocation_id -> allocation for quick access
    sku_alloc_by_id = {str(a.id): a for a in sku_allocations}

    # First, count shipments (primary source of truth)
    for shipment in shipments:
        ship_status_key = shipment.status.value if hasattr(shipment.status, 'value') else str(shipment.status)

        # Collect all allocation IDs covered by this shipment:
        # — the primary allocation_id (always present)
        # — sibling allocations stored in tracking_events items (grouped shipments)
        covered_alloc_ids = set()
        if shipment.allocation_id:
            covered_alloc_ids.add(str(shipment.allocation_id))
        for event in (shipment.tracking_events or []):
            for item in event.get('items', []):
                aid = item.get('allocation_id')
                if aid:
                    covered_alloc_ids.add(str(aid))

        # Find allocations for this SKU that belong to this shipment.
        # Guard against duplicate shipments referencing the same allocation_id:
        # only count each allocation once, for the first shipment that covers it.
        for alloc_id in covered_alloc_ids:
            if alloc_id in counted_allocation_ids:
                continue  # already counted via an earlier shipment
            alloc = sku_alloc_by_id.get(alloc_id)
            if not alloc:
                continue
            if ship_status_key in qty_by_status:
                qty_by_status[ship_status_key] += alloc.quantity_allocated
            counted_allocation_ids.add(alloc_id)
    
    # Second, check allocations with SHIPPED status but no shipment record
    # (fallback for data corruption scenarios)
    for alloc in sku_allocations:
        if str(alloc.id) in counted_allocation_ids:
            continue  # Already counted via shipment
        
        # Check if allocation is marked as SHIPPED but has no shipment
        alloc_status = alloc.status.value if hasattr(alloc.status, 'value') else str(alloc.status)
        if alloc_status == 'SHIPPED' and alloc.shipped_at:
            # Treat as IN_TRANSIT (conservative estimate when no shipment data exists)
            qty_by_status['IN_TRANSIT'] += alloc.quantity_allocated
            counted_allocation_ids.add(str(alloc.id))
    
    # Calculate totals by fulfillment state
    qty_delivered = qty_by_status['DELIVERED']
    qty_in_transit = sum([
        qty_by_status['LABEL_CREATED'],
        qty_by_status['PICKED_UP'],
        qty_by_status['IN_TRANSIT'],
        qty_by_status['OUT_FOR_DELIVERY'],
    ])
    qty_shipped = qty_in_transit + qty_delivered
    
    # Calculate breakdown quantities
    qty_pending = order_line_quantity - total_allocated  # Never allocated
    qty_allocated = total_allocated - qty_shipped  # Allocated but not yet shipped
    qty_backordered = qty_pending  # Items never allocated (same as pending for backorder purposes)
    
    # Determine status
    if qty_delivered >= order_line_quantity:
        status = OrderItemStatus.DELIVERED.value
    elif qty_delivered > 0:
        status = OrderItemStatus.PARTIALLY_DELIVERED.value
    elif qty_in_transit > 0:
        status = OrderItemStatus.OUT_FOR_DELIVERY.value
    elif qty_shipped >= order_line_quantity:
        status = OrderItemStatus.SHIPPED.value
    elif qty_shipped > 0:
        status = OrderItemStatus.PARTIALLY_SHIPPED.value
    elif total_allocated > 0:
        status = OrderItemStatus.ALLOCATED.value
    else:
        status = OrderItemStatus.PENDING.value
    
    return OrderLineQuantityBreakdown(
        status=status,
        quantity_pending=qty_pending,
        quantity_allocated=qty_allocated,
        quantity_backordered=qty_backordered,
        quantity_shipped=qty_shipped,
        quantity_delivered=qty_delivered,
    )


def compute_order_status_from_lines(order_lines: List[Any]) -> str:
    """
    Roll up order status from order line statuses.
    
    Args:
        order_lines: List of OrderItem objects with status field
        
    Returns:
        Aggregated OrderStatus value
    """
    from app.models.postgres.order_models import OrderStatus, OrderItemStatus
    
    if not order_lines:
        return OrderStatus.PENDING.value
    
    line_statuses = [line.status.value if hasattr(line.status, 'value') else str(line.status) for line in order_lines]
    
    # Count status occurrences
    status_counts = {}
    for s in line_statuses:
        status_counts[s] = status_counts.get(s, 0) + 1
    
    total_lines = len(order_lines)
    
    # All delivered
    if status_counts.get(OrderItemStatus.DELIVERED.value, 0) == total_lines:
        return OrderStatus.DELIVERED.value
    
    # Some delivered
    if status_counts.get(OrderItemStatus.DELIVERED.value, 0) > 0:
        return OrderStatus.PARTIALLY_DELIVERED.value
    
    # Partially delivered exists
    if status_counts.get(OrderItemStatus.PARTIALLY_DELIVERED.value, 0) > 0:
        return OrderStatus.PARTIALLY_DELIVERED.value
    
    # All out for delivery
    if status_counts.get(OrderItemStatus.OUT_FOR_DELIVERY.value, 0) == total_lines:
        return OrderStatus.OUT_FOR_DELIVERY.value
    
    # Some out for delivery
    if status_counts.get(OrderItemStatus.OUT_FOR_DELIVERY.value, 0) > 0:
        return OrderStatus.PARTIALLY_DELIVERED.value
    
    # All shipped
    if status_counts.get(OrderItemStatus.SHIPPED.value, 0) == total_lines:
        return OrderStatus.SHIPPED.value
    
    # Some shipped
    if status_counts.get(OrderItemStatus.SHIPPED.value, 0) > 0:
        return OrderStatus.PARTIALLY_SHIPPED.value
    
    # Partially shipped
    if status_counts.get(OrderItemStatus.PARTIALLY_SHIPPED.value, 0) > 0:
        return OrderStatus.PARTIALLY_SHIPPED.value
    
    # Fallback to existing order status flow (picking, packing, ready to ship)
    # These statuses don't cascade from shipments
    return None  # Caller should preserve existing status if None
