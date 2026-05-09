"""Customer accounts router — B2B account management, contacts, and addresses."""
import secrets
import string
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.postgres import get_db
from app.dependencies.auth import get_current_user, require_superadmin
from app.dependencies.tenant import require_b2b
from app.models.postgres.b2b_models import (
    CustomerAccount, AccountType, PricingTier,
    AccountContact, AccountAddress,
)
from app.schemas.b2b import (
    CustomerAccountCreate, CustomerAccountUpdate,
    CustomerAccountResponse, CustomerAccountListResponse, CreditAdjustment,
    AccountContactCreate, AccountContactUpdate, AccountContactResponse,
    AccountAddressCreate, AccountAddressUpdate, AccountAddressResponse,
)

router = APIRouter(
    prefix="/customers",
    tags=["Customer Accounts"],
    dependencies=[Depends(get_current_user), Depends(require_b2b)],
)

_ACCOUNT_ALPHABET = string.ascii_uppercase + string.digits

# Fields that PATCH is explicitly permitted to modify — prevents mass-assignment.
_PATCHABLE_FIELDS = {
    "company_name", "trading_name", "industry", "website", "account_type",
    "contact_name", "contact_email", "contact_phone",
    "credit_limit", "payment_terms",
    "pricing_tier", "tax_exempt", "tax_exempt_id",
    "billing_name", "billing_address1", "billing_address2",
    "billing_city", "billing_state", "billing_postal_code", "billing_country",
    "account_manager_id", "parent_account_id", "approval_threshold",
    "is_active", "notes",
}


def _generate_account_number() -> str:
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    rand = "".join(secrets.choice(_ACCOUNT_ALPHABET) for _ in range(8))
    return f"ACC-{ts}-{rand}"


async def _log_account_event(account_id: str, event_type: str, data: dict, user_id: str = None):
    try:
        from app.database.mongodb import get_mongo_db
        db = await get_mongo_db()
        await db.account_events.insert_one({
            "account_id": account_id,
            "event_type": event_type,
            "timestamp": datetime.now(tz=timezone.utc),
            "user_id": user_id,
            "data": data,
        })
    except Exception:
        pass


async def _get_account_or_404(account_id: UUID, db: AsyncSession) -> CustomerAccount:
    account = await db.get(CustomerAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Customer account not found")
    return account


# ── List ─────────────────────────────────────────────────────────────────────

@router.get("/", response_model=CustomerAccountListResponse,
            dependencies=[Depends(require_superadmin)])
async def list_customer_accounts(
    account_type: Optional[AccountType] = Query(default=None),
    pricing_tier: Optional[PricingTier] = Query(default=None),
    is_active: Optional[bool] = Query(default=None),
    search: Optional[str] = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(CustomerAccount)
    if account_type:
        stmt = stmt.where(CustomerAccount.account_type == account_type)
    if pricing_tier:
        stmt = stmt.where(CustomerAccount.pricing_tier == pricing_tier)
    if is_active is not None:
        stmt = stmt.where(CustomerAccount.is_active == is_active)
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        stmt = stmt.where(or_(
            CustomerAccount.company_name.ilike(like, escape="\\"),
            CustomerAccount.contact_email.ilike(like, escape="\\"),
            CustomerAccount.account_number.ilike(like, escape="\\"),
        ))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = stmt.order_by(CustomerAccount.company_name).offset((page - 1) * page_size).limit(page_size)
    accounts = (await db.execute(stmt)).scalars().all()

    return CustomerAccountListResponse(
        items=[CustomerAccountResponse.model_validate(a) for a in accounts],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


# ── Create ───────────────────────────────────────────────────────────────────

@router.post("/", response_model=CustomerAccountResponse, status_code=201,
             dependencies=[Depends(require_superadmin)])
async def create_customer_account(
    payload: CustomerAccountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # Retry on account_number collision (birthday paradox guard)
    for _ in range(5):
        try:
            account = CustomerAccount(
                account_number=_generate_account_number(),
                company_name=payload.company_name,
                trading_name=payload.trading_name,
                industry=payload.industry,
                website=payload.website,
                account_type=payload.account_type,
                contact_name=payload.contact_name,
                contact_email=payload.contact_email,
                contact_phone=payload.contact_phone,
                credit_limit=payload.credit_limit,
                credit_used=Decimal("0.00"),
                payment_terms=payload.payment_terms.value,
                pricing_tier=payload.pricing_tier,
                tax_exempt=payload.tax_exempt,
                tax_exempt_id=payload.tax_exempt_id,
                billing_name=payload.billing_name,
                billing_address1=payload.billing_address1,
                billing_address2=payload.billing_address2,
                billing_city=payload.billing_city,
                billing_state=payload.billing_state,
                billing_postal_code=payload.billing_postal_code,
                billing_country=payload.billing_country,
                account_manager_id=payload.account_manager_id,
                parent_account_id=payload.parent_account_id,
                approval_threshold=payload.approval_threshold,
                notes=payload.notes,
                metadata_=payload.metadata,
            )
            db.add(account)
            await db.flush()
            break
        except Exception as exc:
            if "unique" in str(exc).lower() and "account_number" in str(exc).lower():
                await db.rollback()
                continue
            raise
    else:
        raise HTTPException(status_code=500, detail="Failed to generate unique account number")

    await db.refresh(account)
    return CustomerAccountResponse.model_validate(account)


# ── Get ──────────────────────────────────────────────────────────────────────

@router.get("/{account_id}", response_model=CustomerAccountResponse,
            dependencies=[Depends(require_superadmin)])
async def get_customer_account(
    account_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    account = await _get_account_or_404(account_id, db)
    return CustomerAccountResponse.model_validate(account)


# ── Update ───────────────────────────────────────────────────────────────────

@router.patch("/{account_id}", response_model=CustomerAccountResponse,
              dependencies=[Depends(require_superadmin)])
async def update_customer_account(
    account_id: UUID,
    payload: CustomerAccountUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    account = await _get_account_or_404(account_id, db)

    old_credit_limit = float(account.credit_limit or 0)
    changed_fields = {}

    for field, value in payload.model_dump(exclude_none=True).items():
        if field not in _PATCHABLE_FIELDS:
            continue
        if field == "payment_terms":
            v = value.value if hasattr(value, "value") else value
            setattr(account, field, v)
            changed_fields[field] = v
        elif field == "metadata":
            account.metadata_ = value
            changed_fields[field] = "<updated>"
        else:
            setattr(account, field, value)
            changed_fields[field] = str(value)

    await db.flush()

    # Audit credit_limit changes
    new_credit_limit = float(account.credit_limit or 0)
    if new_credit_limit != old_credit_limit:
        await _log_account_event(
            str(account_id), "customer_account.credit_limit_changed",
            {"old_credit_limit": old_credit_limit, "new_credit_limit": new_credit_limit,
             "changed_fields": changed_fields},
            user_id=str(current_user.get("id", "")),
        )

    await db.refresh(account)
    return CustomerAccountResponse.model_validate(account)


# ── Credit adjustment ────────────────────────────────────────────────────────

@router.post("/{account_id}/credit-adjustment", response_model=CustomerAccountResponse,
             dependencies=[Depends(require_superadmin)])
async def adjust_credit(
    account_id: UUID,
    payload: CreditAdjustment,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Manually adjust credit_used — e.g. after invoice payment or credit memo."""
    account = await _get_account_or_404(account_id, db)

    old_used = float(account.credit_used or 0)
    new_used = max(0.0, old_used + float(payload.amount))
    credit_limit = float(account.credit_limit or 0)
    if new_used > credit_limit:
        raise HTTPException(
            status_code=400,
            detail=f"Adjustment would set credit_used ({new_used:.2f}) above credit_limit ({credit_limit:.2f})",
        )

    account.credit_used = Decimal(str(new_used))
    await db.flush()

    await _log_account_event(
        str(account_id), "customer_account.credit_adjusted",
        {"old_credit_used": old_used, "new_credit_used": new_used,
         "amount": float(payload.amount), "reason": payload.reason},
        user_id=str(current_user.get("id", "")),
    )

    await db.refresh(account)
    return CustomerAccountResponse.model_validate(account)


# ── Deactivate ───────────────────────────────────────────────────────────────

@router.delete("/{account_id}", status_code=204,
               dependencies=[Depends(require_superadmin)])
async def deactivate_customer_account(
    account_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    account = await _get_account_or_404(account_id, db)
    account.is_active = False
    await db.flush()


# ═════════════════════════════════════════════════════════════════════════════
# Contacts
# ═════════════════════════════════════════════════════════════════════════════

@router.post(
    "/{account_id}/contacts",
    response_model=AccountContactResponse,
    status_code=201,
    dependencies=[Depends(require_superadmin)],
)
async def create_contact(
    account_id: UUID,
    payload: AccountContactCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add a contact to a customer account.

    If is_primary=True, any existing primary contact for the same account is
    demoted first to enforce a single primary per account.
    """
    await _get_account_or_404(account_id, db)

    if payload.is_primary:
        await db.execute(
            update(AccountContact)
            .where(
                AccountContact.customer_account_id == account_id,
                AccountContact.is_primary == True,  # noqa: E712
                AccountContact.is_active == True,  # noqa: E712
            )
            .values(is_primary=False)
        )

    contact = AccountContact(
        customer_account_id=account_id,
        role=payload.role,
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email,
        phone=payload.phone,
        title=payload.title,
        is_primary=payload.is_primary,
        receives_invoices=payload.receives_invoices,
        receives_order_updates=payload.receives_order_updates,
        notes=payload.notes,
    )
    db.add(contact)
    await db.flush()
    await db.refresh(contact)
    return AccountContactResponse.model_validate(contact)


@router.get(
    "/{account_id}/contacts",
    response_model=list[AccountContactResponse],
    dependencies=[Depends(require_superadmin)],
)
async def list_contacts(
    account_id: UUID,
    include_inactive: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    """List contacts for a customer account (active only by default)."""
    await _get_account_or_404(account_id, db)

    stmt = select(AccountContact).where(AccountContact.customer_account_id == account_id)
    if not include_inactive:
        stmt = stmt.where(AccountContact.is_active == True)  # noqa: E712
    stmt = stmt.order_by(AccountContact.is_primary.desc(), AccountContact.first_name)
    contacts = (await db.execute(stmt)).scalars().all()
    return [AccountContactResponse.model_validate(c) for c in contacts]


@router.patch(
    "/{account_id}/contacts/{contact_id}",
    response_model=AccountContactResponse,
    dependencies=[Depends(require_superadmin)],
)
async def update_contact(
    account_id: UUID,
    contact_id: UUID,
    payload: AccountContactUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a contact.  Soft-deleted contacts cannot be updated."""
    await _get_account_or_404(account_id, db)

    contact = await db.get(AccountContact, contact_id)
    if not contact or contact.customer_account_id != account_id:
        raise HTTPException(status_code=404, detail="Contact not found")
    if not contact.is_active:
        raise HTTPException(status_code=409, detail="Contact is inactive; restore it before editing")

    # If promoting to primary, demote the current one first
    if payload.is_primary is True and not contact.is_primary:
        await db.execute(
            update(AccountContact)
            .where(
                AccountContact.customer_account_id == account_id,
                AccountContact.is_primary == True,  # noqa: E712
                AccountContact.is_active == True,  # noqa: E712
            )
            .values(is_primary=False)
        )

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(contact, field, value)

    await db.flush()
    await db.refresh(contact)
    return AccountContactResponse.model_validate(contact)


@router.delete(
    "/{account_id}/contacts/{contact_id}",
    status_code=204,
    dependencies=[Depends(require_superadmin)],
)
async def delete_contact(
    account_id: UUID,
    contact_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a contact (sets is_active=False)."""
    await _get_account_or_404(account_id, db)

    contact = await db.get(AccountContact, contact_id)
    if not contact or contact.customer_account_id != account_id:
        raise HTTPException(status_code=404, detail="Contact not found")

    contact.is_active = False
    await db.flush()


# ═════════════════════════════════════════════════════════════════════════════
# Addresses
# ═════════════════════════════════════════════════════════════════════════════

@router.post(
    "/{account_id}/addresses",
    response_model=AccountAddressResponse,
    status_code=201,
    dependencies=[Depends(require_superadmin)],
)
async def create_address(
    account_id: UUID,
    payload: AccountAddressCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add an address to a customer account.

    If is_default=True, any existing default for the same address_type is
    cleared first to enforce a single default per type.
    """
    await _get_account_or_404(account_id, db)

    if payload.is_default:
        await db.execute(
            update(AccountAddress)
            .where(
                AccountAddress.customer_account_id == account_id,
                AccountAddress.address_type == payload.address_type,
                AccountAddress.is_default == True,  # noqa: E712
                AccountAddress.is_active == True,  # noqa: E712
            )
            .values(is_default=False)
        )

    address = AccountAddress(
        customer_account_id=account_id,
        address_type=payload.address_type,
        label=payload.label,
        address1=payload.address1,
        address2=payload.address2,
        city=payload.city,
        state=payload.state,
        postal_code=payload.postal_code,
        country=payload.country,
        latitude=payload.latitude,
        longitude=payload.longitude,
        is_default=payload.is_default,
    )
    db.add(address)
    await db.flush()
    await db.refresh(address)
    return AccountAddressResponse.model_validate(address)


@router.get(
    "/{account_id}/addresses",
    response_model=list[AccountAddressResponse],
    dependencies=[Depends(require_superadmin)],
)
async def list_addresses(
    account_id: UUID,
    include_inactive: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    """List addresses for a customer account (active only by default)."""
    await _get_account_or_404(account_id, db)

    stmt = select(AccountAddress).where(AccountAddress.customer_account_id == account_id)
    if not include_inactive:
        stmt = stmt.where(AccountAddress.is_active == True)  # noqa: E712
    stmt = stmt.order_by(AccountAddress.is_default.desc(), AccountAddress.address_type, AccountAddress.label)
    addresses = (await db.execute(stmt)).scalars().all()
    return [AccountAddressResponse.model_validate(a) for a in addresses]


@router.patch(
    "/{account_id}/addresses/{address_id}",
    response_model=AccountAddressResponse,
    dependencies=[Depends(require_superadmin)],
)
async def update_address(
    account_id: UUID,
    address_id: UUID,
    payload: AccountAddressUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an address.  Soft-deleted addresses cannot be updated."""
    await _get_account_or_404(account_id, db)

    address = await db.get(AccountAddress, address_id)
    if not address or address.customer_account_id != account_id:
        raise HTTPException(status_code=404, detail="Address not found")
    if not address.is_active:
        raise HTTPException(status_code=409, detail="Address is inactive; restore it before editing")

    # Determine the effective address_type after the update (may change)
    effective_type = payload.address_type if payload.address_type is not None else address.address_type

    # If promoting to default for the effective type, demote the current default first
    if payload.is_default is True and not address.is_default:
        await db.execute(
            update(AccountAddress)
            .where(
                AccountAddress.customer_account_id == account_id,
                AccountAddress.address_type == effective_type,
                AccountAddress.is_default == True,  # noqa: E712
                AccountAddress.is_active == True,  # noqa: E712
            )
            .values(is_default=False)
        )

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(address, field, value)

    await db.flush()
    await db.refresh(address)
    return AccountAddressResponse.model_validate(address)


@router.delete(
    "/{account_id}/addresses/{address_id}",
    status_code=204,
    dependencies=[Depends(require_superadmin)],
)
async def delete_address(
    account_id: UUID,
    address_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete an address (sets is_active=False)."""
    await _get_account_or_404(account_id, db)

    address = await db.get(AccountAddress, address_id)
    if not address or address.customer_account_id != account_id:
        raise HTTPException(status_code=404, detail="Address not found")

    address.is_active = False
    await db.flush()
