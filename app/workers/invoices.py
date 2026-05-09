"""Invoice worker — auto-create invoices from delivered B2B orders; OVERDUE escalation."""
import logging
import secrets
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_sync_session(environment_id: str = ""):
    import re
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.workers.env_utils import get_env_db_url
    sync_url = re.sub(r"\+asyncpg", "", get_env_db_url(environment_id))
    engine = create_engine(sync_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def _generate_invoice_number() -> str:
    month_str = datetime.now(tz=timezone.utc).strftime("%Y%m")
    suffix = secrets.token_hex(3).upper()
    return f"INV-{month_str}-{suffix}"


def _compute_due_date(payment_terms: str, issued: date) -> date:
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


@celery_app.task(
    name="app.workers.invoices.auto_create_invoice",
    queue="notifications",
)
def auto_create_invoice(order_id: str, environment_id: str = ""):
    """
    Idempotent: create an Invoice record (with line items) from a delivered B2B order.
    Called by simulate_delivery after order reaches DELIVERED.
    Does NOT call the HTTP endpoint — uses sync SQLAlchemy directly.
    """
    from app.models.postgres.order_models import Order, OrderType
    from app.models.postgres.b2b_models import CustomerAccount
    from app.models.postgres.invoice_models import Invoice, InvoiceStatus, InvoiceLineItem
    from app.models.postgres.order_models import OrderItem
    # Required mapper imports to avoid DetachedInstanceError / mapper not configured
    import app.models.postgres.auth_models           # noqa: F401
    import app.models.postgres.node_models           # noqa: F401
    import app.models.postgres.connector_models      # noqa: F401
    import app.models.postgres.sourcing_rule_models  # noqa: F401
    import app.models.postgres.lifecycle_models      # noqa: F401
    import app.models.postgres.brand_models          # noqa: F401
    import app.models.postgres.b2b_models            # noqa: F401

    session, engine = _get_sync_session(environment_id)
    try:
        order = session.query(Order).filter(Order.id == order_id).first()
        if not order:
            logger.warning(f"auto_create_invoice: order {order_id} not found")
            return

        order_type_val = order.order_type.value if hasattr(order.order_type, "value") else str(order.order_type or "")
        if order_type_val != "B2B":
            logger.debug(f"auto_create_invoice: order {order_id} is {order_type_val}, not B2B — skipping")
            return

        if not order.customer_account_id:
            logger.debug(f"auto_create_invoice: order {order_id} has no customer_account_id — skipping")
            return

        # Idempotency check
        existing = session.query(Invoice).filter(Invoice.order_id == order.id).first()
        if existing:
            logger.info(f"auto_create_invoice: invoice already exists ({existing.invoice_number}) for order {order_id}")
            return

        account = session.query(CustomerAccount).filter(
            CustomerAccount.id == order.customer_account_id
        ).first()
        if not account:
            logger.warning(f"auto_create_invoice: customer account {order.customer_account_id} not found")
            return

        today = datetime.now(tz=timezone.utc).date()
        payment_terms_snapshot = order.payment_terms or account.payment_terms or "PREPAID"
        due = _compute_due_date(payment_terms_snapshot, today)

        subtotal = Decimal(str(order.subtotal or 0))
        tax_amount = Decimal(str(order.tax_amount or 0))
        total_amount = Decimal(str(order.total_amount or 0))
        currency = order.currency or "USD"

        # Collision-safe invoice number
        inv_number = None
        for _ in range(5):
            candidate = _generate_invoice_number()
            clash = session.query(Invoice).filter(Invoice.invoice_number == candidate).first()
            if not clash:
                inv_number = candidate
                break

        if not inv_number:
            logger.error(f"auto_create_invoice: could not generate unique invoice number for order {order_id}")
            return

        invoice = Invoice(
            invoice_number=inv_number,
            customer_account_id=order.customer_account_id,
            order_id=order.id,
            status=InvoiceStatus.DRAFT,
            subtotal=subtotal,
            tax_amount=tax_amount,
            total_amount=total_amount,
            currency=currency,
            issued_date=today,
            due_date=due,
            payment_terms=payment_terms_snapshot,
            notes=None,
            metadata_={},
        )
        session.add(invoice)
        session.commit()
        session.refresh(invoice)
        logger.info(f"auto_create_invoice: created invoice {inv_number} for order {order_id}")

        # After invoice is saved, populate line items from order items
        order_items = session.query(OrderItem).filter(OrderItem.order_id == order.id).all()
        for item in order_items:
            unit_price = float(item.unit_price or 0)
            discount = float(item.discount_amount or 0)
            qty = float(item.quantity or 1)
            line_total = (unit_price - discount / qty) * qty  # approximate
            line_item = InvoiceLineItem(
                invoice_id=invoice.id,
                order_item_id=item.id,
                sku=item.sku,
                description=item.product_name or item.sku,
                quantity=qty,
                unit_price=unit_price,
                discount_amount=discount,
                tax_amount=0,
                line_total=line_total,
            )
            session.add(line_item)
        session.commit()
        logger.info(
            f"auto_create_invoice: populated {len(order_items)} line items for invoice {inv_number}"
        )

    except Exception as exc:
        session.rollback()
        logger.exception(f"auto_create_invoice failed for order {order_id}: {exc}")
        raise
    finally:
        session.close()
        engine.dispose()


@celery_app.task(
    name="app.workers.invoices.escalate_overdue_invoices",
    queue="notifications",
)
def escalate_overdue_invoices():
    """Daily task: flip SENT invoices past due_date to OVERDUE."""
    from app.models.postgres.invoice_models import Invoice, InvoiceStatus
    import app.models.postgres.auth_models           # noqa: F401
    import app.models.postgres.node_models           # noqa: F401
    import app.models.postgres.connector_models      # noqa: F401
    import app.models.postgres.sourcing_rule_models  # noqa: F401
    import app.models.postgres.lifecycle_models      # noqa: F401
    import app.models.postgres.brand_models          # noqa: F401
    import app.models.postgres.b2b_models            # noqa: F401

    session, engine = _get_sync_session()
    try:
        today = datetime.now(tz=timezone.utc).date()
        overdue = session.query(Invoice).filter(
            Invoice.status == InvoiceStatus.SENT,
            Invoice.due_date < today,
        ).all()

        count = 0
        for inv in overdue:
            inv.status = InvoiceStatus.OVERDUE
            count += 1

        if count:
            session.commit()
            logger.info(f"escalate_overdue_invoices: flipped {count} invoices to OVERDUE")
        else:
            logger.debug("escalate_overdue_invoices: no SENT invoices past due date")
    except Exception as exc:
        session.rollback()
        logger.exception(f"escalate_overdue_invoices failed: {exc}")
        raise
    finally:
        session.close()
        engine.dispose()
