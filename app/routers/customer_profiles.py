"""B2C customer profiles router — lightweight profile linked to order history."""
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import cast, func, or_, select, update
from sqlalchemy import Text as SAText
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.postgres import get_db
from app.dependencies.auth import get_current_user, require_superadmin
from app.models.postgres.customer_models import CustomerProfile, CustomerProfileAddress
from app.models.postgres.order_models import Order, FulfillmentAllocation, Shipment, OrderItem
from app.schemas.customer_profiles import (
    CustomerProfileCreate,
    CustomerProfileUpdate,
    CustomerProfileResponse,
    CustomerProfileListResponse,
    CustomerProfileAddressCreate,
    CustomerProfileAddressUpdate,
    CustomerProfileAddressResponse,
)
from app.schemas.orders import OrderResponse

router = APIRouter(
    prefix="/customers/profiles",
    tags=["Customer Profiles"],
    dependencies=[Depends(get_current_user)],
)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_profile_or_404(customer_id: UUID, db: AsyncSession) -> CustomerProfile:
    result = await db.execute(
        select(CustomerProfile)
        .options(selectinload(CustomerProfile.addresses))
        .where(CustomerProfile.id == customer_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Customer profile not found")
    return profile


async def _load_profile(db: AsyncSession, profile_id) -> CustomerProfile:
    """Reload a profile with addresses eagerly loaded to avoid lazy-load greenlet errors."""
    result = await db.execute(
        select(CustomerProfile)
        .options(selectinload(CustomerProfile.addresses))
        .where(CustomerProfile.id == profile_id)
    )
    return result.scalar_one()


# ── Profile CRUD ──────────────────────────────────────────────────────────────

@router.post(
    "/",
    response_model=CustomerProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a B2C customer profile",
)
async def create_customer_profile(
    payload: CustomerProfileCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Create a profile for a B2C customer identified by email (+ optional brand scope).

    Returns 409 if a profile already exists for the same email + brand_id combination.
    """
    # Check for duplicate
    existing_stmt = select(CustomerProfile).where(
        CustomerProfile.email == payload.email.lower(),
        CustomerProfile.brand_id == payload.brand_id,
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A profile with this email already exists for the given brand.",
        )

    profile = CustomerProfile(
        email=payload.email.lower(),
        first_name=payload.first_name,
        last_name=payload.last_name,
        phone=payload.phone,
        brand_id=payload.brand_id,
        tags=payload.tags or [],
        email_opt_in=payload.email_opt_in,
        sms_opt_in=payload.sms_opt_in,
        preferred_language=payload.preferred_language,
        notes=payload.notes,
    )
    db.add(profile)
    await db.flush()
    loaded = await _load_profile(db, profile.id)
    return CustomerProfileResponse.model_validate(loaded)


@router.get(
    "/",
    response_model=CustomerProfileListResponse,
    summary="List B2C customer profiles",
)
async def list_customer_profiles(
    brand_id: Optional[UUID] = Query(default=None),
    email: Optional[str] = Query(default=None, max_length=255, description="Substring match on email"),
    is_active: Optional[bool] = Query(default=None),
    tags: Optional[List[str]] = Query(default=None, description="Return profiles that have ANY of these tags"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_superadmin),
):
    """List profiles with optional filtering. Superadmin only — response includes financial lifetime stats."""
    stmt = select(CustomerProfile)

    if brand_id is not None:
        stmt = stmt.where(CustomerProfile.brand_id == brand_id)
    if email:
        escaped = email.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(CustomerProfile.email.ilike(f"%{escaped}%", escape="\\"))
    if is_active is not None:
        stmt = stmt.where(CustomerProfile.is_active == is_active)
    if tags:
        # Cast the JSON column to text then search for the quoted string value.
        # Handles PostgreSQL json type (not jsonb); each tag is OR-chained.
        tag_conditions = [
            cast(CustomerProfile.tags, SAText).ilike(f'%"{tag}"%')
            for tag in tags
        ]
        stmt = stmt.where(or_(*tag_conditions))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = (
        stmt
        .options(selectinload(CustomerProfile.addresses))
        .order_by(CustomerProfile.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    profiles = (await db.execute(stmt)).scalars().all()

    return CustomerProfileListResponse(
        items=[CustomerProfileResponse.model_validate(p) for p in profiles],
        total=total,
    )


@router.get(
    "/{customer_id}",
    response_model=CustomerProfileResponse,
    summary="Get a B2C customer profile with addresses",
)
async def get_customer_profile(
    customer_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    profile = await _get_profile_or_404(customer_id, db)
    return CustomerProfileResponse.model_validate(profile)


@router.patch(
    "/{customer_id}",
    response_model=CustomerProfileResponse,
    summary="Update a B2C customer profile (email is immutable)",
)
async def update_customer_profile(
    customer_id: UUID,
    payload: CustomerProfileUpdate,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_superadmin),
):
    """Update mutable profile fields. Email cannot be changed after creation."""
    profile = await _get_profile_or_404(customer_id, db)

    update_data = payload.model_dump(exclude_none=True)
    for field, value in update_data.items():
        if field == "metadata":
            profile.metadata_ = value
        else:
            setattr(profile, field, value)

    await db.flush()
    loaded = await _load_profile(db, profile.id)
    return CustomerProfileResponse.model_validate(loaded)


@router.delete(
    "/{customer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a B2C customer profile",
    dependencies=[Depends(require_superadmin)],
)
async def delete_customer_profile(
    customer_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete — sets is_active=False. Hard deletion is not supported."""
    profile = await _get_profile_or_404(customer_id, db)
    profile.is_active = False
    await db.flush()


# ── Address management ────────────────────────────────────────────────────────

@router.post(
    "/{customer_id}/addresses",
    response_model=CustomerProfileAddressResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a saved address to a customer profile",
)
async def create_profile_address(
    customer_id: UUID,
    payload: CustomerProfileAddressCreate,
    db: AsyncSession = Depends(get_db),
):
    await _get_profile_or_404(customer_id, db)

    if payload.is_default:
        # Unset any existing default address for this customer
        await db.execute(
            update(CustomerProfileAddress)
            .where(
                CustomerProfileAddress.customer_id == customer_id,
                CustomerProfileAddress.is_default == True,  # noqa: E712
            )
            .values(is_default=False)
        )

    address = CustomerProfileAddress(
        customer_id=customer_id,
        label=payload.label,
        is_default=payload.is_default,
        first_name=payload.first_name,
        last_name=payload.last_name,
        address1=payload.address1,
        address2=payload.address2,
        city=payload.city,
        state=payload.state,
        postal_code=payload.postal_code,
        country=payload.country,
        phone=payload.phone,
    )
    db.add(address)
    await db.flush()
    await db.refresh(address)
    return CustomerProfileAddressResponse.model_validate(address)


@router.get(
    "/{customer_id}/addresses",
    response_model=List[CustomerProfileAddressResponse],
    summary="List saved addresses for a customer profile",
)
async def list_profile_addresses(
    customer_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    await _get_profile_or_404(customer_id, db)

    stmt = (
        select(CustomerProfileAddress)
        .where(CustomerProfileAddress.customer_id == customer_id)
        .order_by(CustomerProfileAddress.is_default.desc(), CustomerProfileAddress.created_at)
    )
    addresses = (await db.execute(stmt)).scalars().all()
    return [CustomerProfileAddressResponse.model_validate(a) for a in addresses]


@router.patch(
    "/{customer_id}/addresses/{address_id}",
    response_model=CustomerProfileAddressResponse,
    summary="Update a saved address",
)
async def update_profile_address(
    customer_id: UUID,
    address_id: UUID,
    payload: CustomerProfileAddressUpdate,
    db: AsyncSession = Depends(get_db),
):
    await _get_profile_or_404(customer_id, db)

    address = await db.get(CustomerProfileAddress, address_id)
    if not address or address.customer_id != customer_id:
        raise HTTPException(status_code=404, detail="Address not found")

    # Handle is_default invariant — unset any other default before promoting this one
    if payload.is_default is True and not address.is_default:
        await db.execute(
            update(CustomerProfileAddress)
            .where(
                CustomerProfileAddress.customer_id == customer_id,
                CustomerProfileAddress.is_default == True,  # noqa: E712
                CustomerProfileAddress.id != address_id,
            )
            .values(is_default=False)
        )

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(address, field, value)

    await db.flush()
    await db.refresh(address)
    return CustomerProfileAddressResponse.model_validate(address)


@router.delete(
    "/{customer_id}/addresses/{address_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Hard-delete a saved address",
    dependencies=[Depends(require_superadmin)],
)
async def delete_profile_address(
    customer_id: UUID,
    address_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    await _get_profile_or_404(customer_id, db)

    address = await db.get(CustomerProfileAddress, address_id)
    if not address or address.customer_id != customer_id:
        raise HTTPException(status_code=404, detail="Address not found")

    await db.delete(address)
    await db.flush()


# ── Order history ─────────────────────────────────────────────────────────────

@router.get(
    "/{customer_id}/orders",
    response_model=List[OrderResponse],
    summary="List orders for a B2C customer profile",
)
async def get_customer_orders(
    customer_id: UUID,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Return orders whose customer_email matches the profile's email.

    If the profile has a brand_id, only orders matching that brand (or orders
    with no brand) are returned.  If the profile has no brand_id, all orders for
    that email are returned regardless of brand.
    """
    profile = await _get_profile_or_404(customer_id, db)

    stmt = (
        select(Order)
        .options(
            selectinload(Order.line_items),
            selectinload(Order.fulfillment_allocations).selectinload(FulfillmentAllocation.node),
            selectinload(Order.shipments),
        )
        .where(Order.customer_email == profile.email)
    )

    if profile.brand_id is not None:
        stmt = stmt.where(
            or_(Order.brand_id == profile.brand_id, Order.brand_id.is_(None))
        )

    stmt = stmt.order_by(Order.created_at.desc()).offset(skip).limit(limit)
    orders = (await db.execute(stmt)).scalars().all()
    return [OrderResponse.model_validate(o) for o in orders]


# ── Stats sync ────────────────────────────────────────────────────────────────

@router.post(
    "/{customer_id}/sync-stats",
    response_model=CustomerProfileResponse,
    summary="Recalculate lifetime stats from orders table (superadmin only)",
    dependencies=[Depends(require_superadmin)],
)
async def sync_customer_stats(
    customer_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Recalculate total_orders, total_spent, and last_order_at by aggregating
    orders matching this profile's email (and brand scope).

    Safe to call repeatedly — fully idempotent.
    """
    profile = await _get_profile_or_404(customer_id, db)

    base_filter = Order.customer_email == profile.email
    if profile.brand_id is not None:
        brand_filter = or_(Order.brand_id == profile.brand_id, Order.brand_id.is_(None))
        filter_clause = base_filter & brand_filter
    else:
        filter_clause = base_filter

    agg_stmt = select(
        func.count(Order.id).label("order_count"),
        func.coalesce(func.sum(Order.total_amount), 0).label("total_spent"),
        func.max(Order.created_at).label("last_order_at"),
    ).where(filter_clause)

    row = (await db.execute(agg_stmt)).one()

    profile.total_orders = row.order_count
    profile.total_spent = Decimal(str(row.total_spent))
    profile.last_order_at = row.last_order_at

    await db.flush()
    loaded = await _load_profile(db, profile.id)
    return CustomerProfileResponse.model_validate(loaded)
