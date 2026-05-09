"""Invoices router — B2B accounts receivable management."""
import secrets
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.postgres import get_db
from app.dependencies.auth import get_current_user, require_superadmin
from app.models.postgres.b2b_models import CustomerAccount
from app.models.postgres.invoice_models import (
    Invoice,
    InvoicePayment,
    InvoiceStatus,
    CreditMemo,
    CreditMemoStatus,
    PaymentMethod,
)
from app.schemas.invoices import (
    ARAgingBucket,
    ARAgingResponse,
    CreditMemoCreate,
    CreditMemoResponse,
    InvoiceCreate,
    InvoiceListResponse,
    InvoiceResponse,
    InvoiceStatusUpdate,
    PaymentCreate,
    PaymentResponse,
)

router = APIRouter(
    prefix="/invoices",
    tags=["Invoices"],
    dependencies=[Depends(get_current_user), Depends(require_superadmin)],
)

# ---------------------------------------------------------------------------
# Sub-router for credit memos (mounted without /invoices prefix)
# ---------------------------------------------------------------------------
credit_memo_router = APIRouter(
    prefix="/credit-memos",
    tags=["Credit Memos"],
    dependencies=[Depends(get_current_user), Depends(require_superadmin)],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_invoice_number() -> str:
    month_str = datetime.now(tz=timezone.utc).strftime("%Y%m")
    suffix = secrets.token_hex(3).upper()  # 6 hex chars
    return f"INV-{month_str}-{suffix}"


def _generate_memo_number() -> str:
    month_str = datetime.now(tz=timezone.utc).strftime("%Y%m")
    suffix = secrets.token_hex(3).upper()  # 6 hex chars
    return f"CM-{month_str}-{suffix}"


def _compute_due_date(payment_terms: str, issued: date) -> date:
    """Compute due date from payment_terms snapshot string."""
    terms_map = {
        "NET_15": 15,
        "NET_30": 30,
        "NET_60": 60,
        "NET_90": 90,
        "NET30": 30,
        "NET60": 60,
        "NET90": 90,
        "COD": 0,
        "UPON_RECEIPT": 0,
        "PREPAID": 0,
    }
    days = terms_map.get(payment_terms.upper(), 0)
    return issued + timedelta(days=days)


async def _load_invoice(db: AsyncSession, invoice_id: UUID) -> Invoice:
    """Load invoice with all eager relationships needed for responses."""
    result = await db.execute(
        select(Invoice)
        .options(
            selectinload(Invoice.customer_account),
            selectinload(Invoice.order),
            selectinload(Invoice.line_items),
            selectinload(Invoice.payments),
        )
        .where(Invoice.id == invoice_id)
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return inv


async def _create_invoice_from_order_internal(
    db: AsyncSession, order
) -> Invoice:
    """
    Core idempotent logic for auto-creating an invoice from a delivered B2B order.
    Returns existing invoice if one already exists for this order_id.
    """
    # Idempotency check
    existing_result = await db.execute(
        select(Invoice).where(Invoice.order_id == order.id)
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        return existing

    if not order.customer_account_id:
        raise HTTPException(
            status_code=400,
            detail="Order has no customer_account_id — cannot create B2B invoice",
        )

    account = await db.get(CustomerAccount, order.customer_account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Customer account not found")

    today = datetime.now(tz=timezone.utc).date()
    payment_terms_snapshot = order.payment_terms or account.payment_terms or "PREPAID"
    due = _compute_due_date(payment_terms_snapshot, today)

    subtotal = Decimal(str(order.subtotal or 0))
    tax_amount = Decimal(str(order.tax_amount or 0))
    total_amount = Decimal(str(order.total_amount or 0))

    # Collision-safe invoice number generation
    inv_number = None
    for _ in range(5):
        candidate = _generate_invoice_number()
        clash = await db.execute(select(Invoice).where(Invoice.invoice_number == candidate))
        if not clash.scalar_one_or_none():
            inv_number = candidate
            break

    if not inv_number:
        raise HTTPException(status_code=500, detail="Could not generate unique invoice number")

    invoice = Invoice(
        invoice_number=inv_number,
        customer_account_id=order.customer_account_id,
        order_id=order.id,
        status=InvoiceStatus.DRAFT,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total_amount=total_amount,
        currency=order.currency or "USD",
        issued_date=today,
        due_date=due,
        payment_terms=payment_terms_snapshot,
        notes=None,
        metadata_={},
    )
    db.add(invoice)
    await db.flush()
    await db.refresh(invoice)
    return invoice


# ---------------------------------------------------------------------------
# Endpoints — ordering matters: static paths must precede /{invoice_id}
# ---------------------------------------------------------------------------

@router.get("/aging", response_model=ARAgingResponse)
async def get_ar_aging(db: AsyncSession = Depends(get_db)):
    """Accounts receivable aging report: current / 1-30 / 31-60 / 61-90 / 90+ days."""
    today = datetime.now(tz=timezone.utc).date()

    stmt = select(Invoice).where(
        Invoice.status.notin_([InvoiceStatus.PAID, InvoiceStatus.VOID, InvoiceStatus.DRAFT])
    )
    result = await db.execute(stmt)
    invoices = result.scalars().all()

    current_bucket = ARAgingBucket(count=0, total_amount=Decimal("0"))
    bucket_1_30 = ARAgingBucket(count=0, total_amount=Decimal("0"))
    bucket_31_60 = ARAgingBucket(count=0, total_amount=Decimal("0"))
    bucket_61_90 = ARAgingBucket(count=0, total_amount=Decimal("0"))
    bucket_over_90 = ARAgingBucket(count=0, total_amount=Decimal("0"))
    total_outstanding = Decimal("0")

    for inv in invoices:
        amount = Decimal(str(inv.total_amount or 0))
        days_overdue = (today - inv.due_date).days

        if days_overdue <= 0:
            current_bucket.count += 1
            current_bucket.total_amount += amount
        elif days_overdue <= 30:
            bucket_1_30.count += 1
            bucket_1_30.total_amount += amount
        elif days_overdue <= 60:
            bucket_31_60.count += 1
            bucket_31_60.total_amount += amount
        elif days_overdue <= 90:
            bucket_61_90.count += 1
            bucket_61_90.total_amount += amount
        else:
            bucket_over_90.count += 1
            bucket_over_90.total_amount += amount

        total_outstanding += amount

    return ARAgingResponse(
        current=current_bucket,
        days_1_30=bucket_1_30,
        days_31_60=bucket_31_60,
        days_61_90=bucket_61_90,
        over_90=bucket_over_90,
        total_outstanding=total_outstanding,
    )


@router.get("/account/{account_id}", response_model=InvoiceListResponse)
async def list_invoices_for_account(
    account_id: UUID,
    status: Optional[InvoiceStatus] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List all invoices for a specific customer account."""
    stmt = select(Invoice).where(Invoice.customer_account_id == account_id)
    if status:
        stmt = stmt.where(Invoice.status == status)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = (
        stmt
        .options(
            selectinload(Invoice.customer_account),
            selectinload(Invoice.order),
            selectinload(Invoice.line_items),
            selectinload(Invoice.payments),
        )
        .order_by(Invoice.issued_date.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    invoices = (await db.execute(stmt)).scalars().all()

    return InvoiceListResponse(
        items=[InvoiceResponse.from_orm_with_relations(inv) for inv in invoices],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/", response_model=InvoiceListResponse)
async def list_invoices(
    customer_account_id: Optional[UUID] = Query(default=None),
    status: Optional[InvoiceStatus] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List invoices with optional filters."""
    stmt = select(Invoice)
    if customer_account_id:
        stmt = stmt.where(Invoice.customer_account_id == customer_account_id)
    if status:
        stmt = stmt.where(Invoice.status == status)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = (
        stmt
        .options(
            selectinload(Invoice.customer_account),
            selectinload(Invoice.order),
            selectinload(Invoice.line_items),
            selectinload(Invoice.payments),
        )
        .order_by(Invoice.issued_date.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    invoices = (await db.execute(stmt)).scalars().all()

    return InvoiceListResponse(
        items=[InvoiceResponse.from_orm_with_relations(inv) for inv in invoices],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.post("/", response_model=InvoiceResponse, status_code=201)
async def create_invoice(
    payload: InvoiceCreate,
    db: AsyncSession = Depends(get_db),
):
    """Manually create an invoice for a customer account."""
    from sqlalchemy.orm import selectinload as sil
    from app.models.postgres.order_models import Order

    account = await db.get(CustomerAccount, payload.customer_account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Customer account not found")

    order = None
    if payload.order_id:
        order = await db.get(Order, payload.order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        if order.customer_account_id != payload.customer_account_id:
            raise HTTPException(
                status_code=400,
                detail="Order does not belong to the specified customer account",
            )
        # Idempotency: if an invoice already exists for this order return it
        existing_result = await db.execute(
            select(Invoice)
            .options(
                sil(Invoice.customer_account),
                sil(Invoice.order),
                sil(Invoice.line_items),
                sil(Invoice.payments),
            )
            .where(Invoice.order_id == payload.order_id)
        )
        existing = existing_result.scalar_one_or_none()
        if existing:
            return InvoiceResponse.from_orm_with_relations(existing)

    today = datetime.now(tz=timezone.utc).date()
    payment_terms_snapshot = account.payment_terms or "PREPAID"
    due = _compute_due_date(payment_terms_snapshot, today)

    subtotal: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    currency = "USD"

    if order:
        subtotal = Decimal(str(order.subtotal or 0))
        tax_amount = Decimal(str(order.tax_amount or 0))
        total_amount = Decimal(str(order.total_amount or 0))
        currency = order.currency or "USD"
        payment_terms_snapshot = order.payment_terms or payment_terms_snapshot
        due = _compute_due_date(payment_terms_snapshot, today)
    else:
        subtotal = Decimal("0.00")
        tax_amount = Decimal("0.00")
        total_amount = Decimal("0.00")

    inv_number = None
    for _ in range(5):
        candidate = _generate_invoice_number()
        clash = await db.execute(select(Invoice).where(Invoice.invoice_number == candidate))
        if not clash.scalar_one_or_none():
            inv_number = candidate
            break

    if not inv_number:
        raise HTTPException(status_code=500, detail="Could not generate unique invoice number")

    invoice = Invoice(
        invoice_number=inv_number,
        customer_account_id=payload.customer_account_id,
        order_id=payload.order_id,
        status=InvoiceStatus.DRAFT,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total_amount=total_amount,
        currency=currency,
        issued_date=today,
        due_date=due,
        payment_terms=payment_terms_snapshot,
        notes=payload.notes,
        metadata_={},
    )
    db.add(invoice)
    await db.flush()

    result = await db.execute(
        select(Invoice)
        .options(
            selectinload(Invoice.customer_account),
            selectinload(Invoice.order),
            selectinload(Invoice.line_items),
            selectinload(Invoice.payments),
        )
        .where(Invoice.id == invoice.id)
    )
    inv = result.scalar_one()
    return InvoiceResponse.from_orm_with_relations(inv)


@router.post("/from-order/{order_id}", response_model=InvoiceResponse, status_code=201)
async def create_invoice_from_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Auto-create an invoice from a delivered B2B order.
    Idempotent — returns the existing invoice if already created for this order.
    """
    from app.models.postgres.order_models import Order, OrderType

    result = await db.execute(
        select(Order)
        .options(selectinload(Order.line_items))
        .where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.order_type != OrderType.B2B.value and order.order_type != "B2B":
        raise HTTPException(status_code=400, detail="Only B2B orders can be invoiced")
    if not order.customer_account_id:
        raise HTTPException(status_code=400, detail="Order has no linked customer account")

    invoice = await _create_invoice_from_order_internal(db, order)
    await db.commit()

    result2 = await db.execute(
        select(Invoice)
        .options(
            selectinload(Invoice.customer_account),
            selectinload(Invoice.order),
            selectinload(Invoice.line_items),
            selectinload(Invoice.payments),
        )
        .where(Invoice.id == invoice.id)
    )
    inv = result2.scalar_one()
    return InvoiceResponse.from_orm_with_relations(inv)


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(invoice_id: UUID, db: AsyncSession = Depends(get_db)):
    """Retrieve a single invoice by ID, including line items, payments, and relations."""
    inv = await _load_invoice(db, invoice_id)
    return InvoiceResponse.from_orm_with_relations(inv)


@router.patch("/{invoice_id}/status", response_model=InvoiceResponse)
async def update_invoice_status(
    invoice_id: UUID,
    payload: InvoiceStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Update invoice status.
    On PAID: set paid_date=today and release credit_used on the customer account.
    """
    inv = await _load_invoice(db, invoice_id)

    old_status = inv.status
    inv.status = payload.status
    if payload.notes:
        inv.notes = payload.notes

    today = datetime.now(tz=timezone.utc).date()

    if payload.status == InvoiceStatus.PAID and old_status != InvoiceStatus.PAID:
        inv.paid_date = today
        account = await db.get(CustomerAccount, inv.customer_account_id)
        if account:
            invoice_total = float(inv.total_amount or 0)
            current_used = float(account.credit_used or 0)
            account.credit_used = Decimal(str(max(0.0, current_used - invoice_total)))

            try:
                from app.database.mongodb import get_mongo_db
                mdb = await get_mongo_db()
                await mdb.order_events.insert_one({
                    "order_id": str(inv.order_id) if inv.order_id else None,
                    "event_type": "customer_account.invoice_paid",
                    "timestamp": datetime.now(tz=timezone.utc),
                    "data": {
                        "invoice_id": str(inv.id),
                        "invoice_number": inv.invoice_number,
                        "amount_paid": invoice_total,
                        "credit_used_before": current_used,
                        "credit_used_after": float(account.credit_used),
                        "account_id": str(account.id),
                    },
                })
            except Exception:
                pass

    await db.flush()

    result = await db.execute(
        select(Invoice)
        .options(
            selectinload(Invoice.customer_account),
            selectinload(Invoice.order),
            selectinload(Invoice.line_items),
            selectinload(Invoice.payments),
        )
        .where(Invoice.id == invoice_id)
    )
    inv = result.scalar_one()
    return InvoiceResponse.from_orm_with_relations(inv)


# ---------------------------------------------------------------------------
# Feature 2: Partial payment recording
# ---------------------------------------------------------------------------

@router.post("/{invoice_id}/payments", response_model=InvoiceResponse, status_code=201)
async def record_payment(
    invoice_id: UUID,
    payload: PaymentCreate,
    db: AsyncSession = Depends(get_db),
):
    """Record a payment against an invoice; auto-transitions to PAID when fully settled."""
    inv = await _load_invoice(db, invoice_id)

    if inv.status in (InvoiceStatus.PAID, InvoiceStatus.VOID):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot record payment on invoice with status {inv.status.value}",
        )

    # Validate payment method
    try:
        payment_method_enum = PaymentMethod(payload.payment_method.upper())
    except ValueError:
        valid = [m.value for m in PaymentMethod]
        raise HTTPException(
            status_code=422,
            detail=f"Invalid payment_method. Must be one of: {valid}",
        )

    payment = InvoicePayment(
        invoice_id=inv.id,
        amount=payload.amount,
        payment_date=payload.payment_date,
        payment_method=payment_method_enum,
        reference_number=payload.reference_number,
        notes=payload.notes,
    )
    db.add(payment)
    await db.flush()

    # Reload to get updated payments list for amount_paid calculation
    result = await db.execute(
        select(Invoice)
        .options(
            selectinload(Invoice.customer_account),
            selectinload(Invoice.order),
            selectinload(Invoice.line_items),
            selectinload(Invoice.payments),
        )
        .where(Invoice.id == invoice_id)
    )
    inv = result.scalar_one()

    # Auto-transition to PAID if fully settled
    if inv.amount_paid >= float(inv.total_amount or 0) and inv.status != InvoiceStatus.PAID:
        today = datetime.now(tz=timezone.utc).date()
        inv.status = InvoiceStatus.PAID
        inv.paid_date = today

        # Release credit_used on account
        account = await db.get(CustomerAccount, inv.customer_account_id)
        if account:
            invoice_total = float(inv.total_amount or 0)
            current_used = float(account.credit_used or 0)
            account.credit_used = Decimal(str(max(0.0, current_used - invoice_total)))

            try:
                from app.database.mongodb import get_mongo_db
                mdb = await get_mongo_db()
                await mdb.order_events.insert_one({
                    "order_id": str(inv.order_id) if inv.order_id else None,
                    "event_type": "customer_account.invoice_paid",
                    "timestamp": datetime.now(tz=timezone.utc),
                    "data": {
                        "invoice_id": str(inv.id),
                        "invoice_number": inv.invoice_number,
                        "amount_paid": inv.amount_paid,
                        "credit_used_before": current_used,
                        "credit_used_after": float(account.credit_used),
                        "account_id": str(account.id),
                        "via": "partial_payments_settled",
                    },
                })
            except Exception:
                pass

        await db.flush()

        # Reload after status update
        result2 = await db.execute(
            select(Invoice)
            .options(
                selectinload(Invoice.customer_account),
                selectinload(Invoice.order),
                selectinload(Invoice.line_items),
                selectinload(Invoice.payments),
            )
            .where(Invoice.id == invoice_id)
        )
        inv = result2.scalar_one()

    return InvoiceResponse.from_orm_with_relations(inv)


@router.get("/{invoice_id}/payments", response_model=List[PaymentResponse])
async def list_payments(invoice_id: UUID, db: AsyncSession = Depends(get_db)):
    """List all payments recorded against an invoice."""
    # Confirm invoice exists
    inv_check = await db.get(Invoice, invoice_id)
    if not inv_check:
        raise HTTPException(status_code=404, detail="Invoice not found")

    result = await db.execute(
        select(InvoicePayment)
        .where(InvoicePayment.invoice_id == invoice_id)
        .order_by(InvoicePayment.payment_date.asc(), InvoicePayment.created_at.asc())
    )
    payments = result.scalars().all()
    return [PaymentResponse.model_validate(p) for p in payments]


# ---------------------------------------------------------------------------
# Feature 3: Credit memo endpoints (under /invoices/{invoice_id}/credit-memos)
# ---------------------------------------------------------------------------

@router.post("/{invoice_id}/credit-memos", response_model=CreditMemoResponse, status_code=201)
async def create_credit_memo(
    invoice_id: UUID,
    payload: CreditMemoCreate,
    db: AsyncSession = Depends(get_db),
):
    """Issue a credit memo against an invoice."""
    inv = await db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Generate unique memo number
    memo_number = None
    for _ in range(5):
        candidate = _generate_memo_number()
        clash = await db.execute(
            select(CreditMemo).where(CreditMemo.memo_number == candidate)
        )
        if not clash.scalar_one_or_none():
            memo_number = candidate
            break

    if not memo_number:
        raise HTTPException(status_code=500, detail="Could not generate unique memo number")

    memo = CreditMemo(
        memo_number=memo_number,
        customer_account_id=inv.customer_account_id,
        invoice_id=inv.id,
        order_id=inv.order_id,
        status=CreditMemoStatus.DRAFT,
        amount=payload.amount,
        currency=inv.currency,
        reason=payload.reason,
        notes=payload.notes,
    )
    db.add(memo)
    await db.flush()
    await db.refresh(memo)
    return CreditMemoResponse.model_validate(memo)


# ---------------------------------------------------------------------------
# Credit memo apply endpoint (prefix: /credit-memos, no /invoices prefix)
# ---------------------------------------------------------------------------

@credit_memo_router.patch("/{memo_id}/apply", response_model=CreditMemoResponse)
async def apply_credit_memo(memo_id: UUID, db: AsyncSession = Depends(get_db)):
    """Apply a credit memo: reduce linked invoice outstanding balance and release customer credit_used."""
    result = await db.execute(
        select(CreditMemo).where(CreditMemo.id == memo_id)
    )
    memo = result.scalar_one_or_none()
    if not memo:
        raise HTTPException(status_code=404, detail="Credit memo not found")

    if memo.status == CreditMemoStatus.APPLIED:
        raise HTTPException(status_code=400, detail="Credit memo already applied")
    if memo.status == CreditMemoStatus.VOID:
        raise HTTPException(status_code=400, detail="Cannot apply a voided credit memo")

    today = datetime.now(tz=timezone.utc).date()
    memo.status = CreditMemoStatus.APPLIED
    memo.applied_date = today

    # Release credit_used on account by memo.amount
    account = await db.get(CustomerAccount, memo.customer_account_id)
    if account:
        memo_amount = float(memo.amount or 0)
        current_used = float(account.credit_used or 0)
        account.credit_used = Decimal(str(max(0.0, current_used - memo_amount)))

    await db.flush()
    await db.refresh(memo)
    return CreditMemoResponse.model_validate(memo)
