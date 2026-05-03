"""
Lifecycle Engine
================
Resolves which lifecycle applies to an order, validates status transitions,
and tells the fulfillment pipeline what automated action to fire next.

Used by:
  - app/routers/orders.py    (transition validation)
  - app/routers/lifecycles.py (resolve endpoint)
  - app/workers/fulfillment.py (what status to set after packing)
  - app/workers/carrier.py    (should carrier be booked?)
"""
import logging
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.postgres.lifecycle_models import Lifecycle, LifecycleStep

logger = logging.getLogger(__name__)

# ── Action type constants ────────────────────────────────────────────────────

ACTION_BOOK_SHIPMENT = "book_shipment"
ACTION_SEND_PICKUP_READY = "send_pickup_ready"
ACTION_SIMULATE_DELIVERY = "simulate_delivery"

# Fulfillment types that must never trigger carrier booking
PICKUP_TYPES = {"STORE_PICKUP", "CURBSIDE_PICKUP"}

# Fulfillment types that restrict sourcing to retail/dark stores
SHIP_FROM_STORE_TYPES = {"SHIP_FROM_STORE"}


# ── Resolution ──────────────────────────────────────────────────────────────

async def resolve_lifecycle(
    db: AsyncSession,
    fulfillment_type: str,
    channel: Optional[str] = None,
) -> Tuple[Optional[Lifecycle], str]:
    """
    Find the best-matching active lifecycle for the given context.

    Resolution priority:
      1. fulfillment_type match AND channel match
      2. fulfillment_type match, no channel restriction (channels=[])
      3. is_default=True lifecycle
      4. (None, "none") — no lifecycle found; callers fall back to hardcoded rules

    Returns (lifecycle_or_None, matched_on_string).
    """
    result = await db.execute(
        select(Lifecycle)
        .options(selectinload(Lifecycle.steps))
        .where(Lifecycle.is_active == True)
    )
    all_lcs = result.scalars().all()

    exact_match = None      # fulfillment_type + channel
    type_match = None       # fulfillment_type only
    default_lc = None       # is_default fallback

    for lc in all_lcs:
        ft_list = lc.fulfillment_types or []
        ch_list = lc.channels or []

        ft_matches = (not ft_list) or (fulfillment_type in ft_list)
        if not ft_matches:
            continue

        ch_matches = (not ch_list) or (channel and channel in ch_list)

        if ft_list and ch_list and ch_matches:
            exact_match = lc
        elif ft_list and not ch_list and type_match is None:
            type_match = lc

        if lc.is_default and default_lc is None:
            default_lc = lc

    if exact_match:
        return exact_match, "exact"
    if type_match:
        return type_match, "fulfillment_type"
    if default_lc:
        return default_lc, "default"
    return None, "none"


async def resolve_lifecycle_for_order(db: AsyncSession, order) -> Tuple[Optional[Lifecycle], str]:
    """Convenience wrapper that reads fulfillment_type and channel from an Order ORM object."""
    ft = order.fulfillment_type.value if hasattr(order.fulfillment_type, "value") else str(order.fulfillment_type or "")
    ch = order.channel.value if hasattr(order.channel, "value") else str(order.channel or "")
    return await resolve_lifecycle(db, ft, ch)


# ── Sync versions for Celery workers ────────────────────────────────────────

def resolve_lifecycle_sync(environment_id: str, fulfillment_type: str, channel: str = "") -> Tuple[Optional[object], str]:
    """
    Synchronous version for use inside Celery tasks (which use sync SQLAlchemy).
    Returns (lifecycle_dict_or_None, matched_on).

    lifecycle_dict shape:
      {
        "id": str,
        "name": str,
        "fulfillment_types": [...],
        "steps": [
          {"status": str, "allowed_next_statuses": [...], "action_type": str|None, "sla_hours": float|None},
          ...
        ]
      }
    """
    import re
    from sqlalchemy import create_engine, text
    from app.workers.env_utils import get_env_db_url

    sync_url = re.sub(r"\+asyncpg", "", get_env_db_url(environment_id))
    engine = create_engine(sync_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT l.id, l.name, l.fulfillment_types, l.channels, l.is_default,
                       ls.status, ls.allowed_next_statuses, ls.action_type, ls.sla_hours, ls.step_order
                FROM lifecycles l
                JOIN lifecycle_steps ls ON ls.lifecycle_id = l.id
                WHERE l.is_active = TRUE
                ORDER BY l.id, ls.step_order
            """)).fetchall()
    except Exception as exc:
        logger.warning(f"lifecycle_engine: DB query failed: {exc}")
        return None, "none"
    finally:
        engine.dispose()

    # Group rows into lifecycle dicts
    lcs: dict = {}
    for row in rows:
        lid = str(row[0])
        if lid not in lcs:
            lcs[lid] = {
                "id": lid,
                "name": row[1],
                "fulfillment_types": row[2] or [],
                "channels": row[3] or [],
                "is_default": bool(row[4]),
                "steps": [],
            }
        lcs[lid]["steps"].append({
            "status": row[5],
            "allowed_next_statuses": row[6] or [],
            "action_type": row[7],
            "sla_hours": row[8],
            "step_order": row[9],
        })

    exact_match = None
    type_match = None
    default_lc = None

    for lc in lcs.values():
        ft_list = lc["fulfillment_types"]
        ch_list = lc["channels"]

        ft_matches = (not ft_list) or (fulfillment_type in ft_list)
        if not ft_matches:
            continue

        ch_matches = (not ch_list) or (channel and channel in ch_list)

        if ft_list and ch_list and ch_matches and exact_match is None:
            exact_match = lc
        elif ft_list and not ch_list and type_match is None:
            type_match = lc

        if lc["is_default"] and default_lc is None:
            default_lc = lc

    if exact_match:
        return exact_match, "exact"
    if type_match:
        return type_match, "fulfillment_type"
    if default_lc:
        return default_lc, "default"
    return None, "none"


# ── Transition validation ────────────────────────────────────────────────────

async def validate_transition(
    db: AsyncSession,
    order,
    new_status: str,
) -> Tuple[bool, str]:
    """
    Return (allowed: bool, reason: str).

    If no lifecycle is configured for the order, all transitions are allowed
    (backward-compatible permissive default).
    """
    lc, matched_on = await resolve_lifecycle_for_order(db, order)
    if not lc or not lc.steps:
        return True, "no lifecycle configured"

    current = order.status.value if hasattr(order.status, "value") else str(order.status)
    step = _get_step(lc.steps, current)
    if not step:
        return True, f"status {current!r} not in lifecycle {lc.name!r}"

    allowed = new_status in (step.allowed_next_statuses or [])
    if allowed:
        return True, "ok"
    return False, (
        f"lifecycle '{lc.name}' does not allow transition "
        f"{current!r} → {new_status!r}. "
        f"Allowed: {step.allowed_next_statuses}"
    )


# ── Next-status helpers ──────────────────────────────────────────────────────

def get_post_packing_status(lc_dict: Optional[dict], fulfillment_type: str) -> str:
    """
    Given the resolved lifecycle dict (from resolve_lifecycle_sync), return the
    status that should follow PACKING.

    Pickup types  → READY_FOR_PICKUP
    Shipping types → READY_TO_SHIP
    No lifecycle configured → derive from fulfillment_type
    """
    if lc_dict:
        packing_step = next(
            (s for s in lc_dict["steps"] if s["status"] == "PACKING"),
            None,
        )
        if packing_step:
            nexts = packing_step["allowed_next_statuses"] or []
            # Prefer READY_FOR_PICKUP or READY_TO_SHIP over other allowed statuses
            for preferred in ("READY_FOR_PICKUP", "READY_TO_SHIP"):
                if preferred in nexts:
                    return preferred
            if nexts:
                return nexts[0]

    # Fallback: derive purely from fulfillment type
    if fulfillment_type in PICKUP_TYPES:
        return "READY_FOR_PICKUP"
    return "READY_TO_SHIP"


def get_action_for_status(lc_dict: Optional[dict], status: str, fulfillment_type: str) -> Optional[str]:
    """
    Return the action_type configured for entering `status`, or derive it from
    fulfillment_type if no lifecycle is set.
    """
    if lc_dict:
        step = next((s for s in lc_dict["steps"] if s["status"] == status), None)
        if step:
            return step.get("action_type")

    # Hardcoded fallback
    if status == "READY_TO_SHIP":
        return ACTION_BOOK_SHIPMENT
    if status == "READY_FOR_PICKUP":
        return ACTION_SEND_PICKUP_READY
    if status == "SHIPPED":
        return ACTION_SIMULATE_DELIVERY
    return None


def should_book_carrier(lc_dict: Optional[dict], fulfillment_type: str) -> bool:
    """
    True if the lifecycle (or fulfillment type fallback) expects carrier booking.
    Pickup types never book a carrier; shipping types always do.
    """
    if fulfillment_type in PICKUP_TYPES:
        return False

    if lc_dict:
        # Carrier booking is needed if any step has action_type == "book_shipment"
        for step in lc_dict.get("steps", []):
            if step.get("action_type") == ACTION_BOOK_SHIPMENT:
                return True
        # No book_shipment action in lifecycle → skip carrier
        return False

    # No lifecycle — default to shipping types always book carrier
    return True


# ── Internal helpers ─────────────────────────────────────────────────────────

def _get_step(steps, status: str) -> Optional[LifecycleStep]:
    for s in steps:
        s_status = s.status if isinstance(s, LifecycleStep) else s.get("status")
        if s_status == status:
            return s
    return None
