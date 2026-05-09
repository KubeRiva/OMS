"""Invoice models — B2B accounts receivable."""
import uuid
import enum
from datetime import datetime, date

from sqlalchemy import (
    Column, String, Date, DateTime, Numeric,
    Enum as SAEnum, Text, ForeignKey, Index, JSON,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.postgres import Base


class InvoiceStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    VOID = "VOID"


class PaymentMethod(str, enum.Enum):
    CHECK = "CHECK"
    WIRE = "WIRE"
    ACH = "ACH"
    CREDIT_CARD = "CREDIT_CARD"
    CASH = "CASH"
    OTHER = "OTHER"


class CreditMemoStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    APPLIED = "APPLIED"
    VOID = "VOID"


class Invoice(Base):
    """B2B invoice — issued after order delivery; tracks receivables."""
    __tablename__ = "invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Human-readable identifier: INV-{YYYYMM}-{6-char hex}
    invoice_number = Column(String(50), unique=True, nullable=False, index=True)

    # Account (required) and order (optional — future: consolidated invoices)
    customer_account_id = Column(
        UUID(as_uuid=True), ForeignKey("customer_accounts.id"), nullable=False, index=True
    )
    order_id = Column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True
    )

    status = Column(SAEnum(InvoiceStatus), default=InvoiceStatus.DRAFT, nullable=False, index=True)

    # Financials
    subtotal = Column(Numeric(12, 2), nullable=False)
    tax_amount = Column(Numeric(12, 2), nullable=False, default=0)
    total_amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)

    # Dates
    issued_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    paid_date = Column(Date, nullable=True)

    # Snapshot of payment terms at invoice creation
    payment_terms = Column(String(20), nullable=False)

    notes = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSON, default=dict)

    # Audit timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    customer_account = relationship("CustomerAccount", lazy="select")
    order = relationship("Order", lazy="select")
    line_items = relationship(
        "InvoiceLineItem",
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy="select",
    )
    payments = relationship(
        "InvoicePayment",
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy="select",
    )

    @property
    def amount_paid(self) -> float:
        return sum(float(p.amount) for p in self.payments) if self.payments else 0.0

    @property
    def amount_due(self) -> float:
        return max(0.0, float(self.total_amount or 0) - self.amount_paid)

    __table_args__ = (
        Index("ix_invoices_account_status", "customer_account_id", "status"),
        Index("ix_invoices_due_date", "due_date"),
        Index("ix_invoices_order_id", "order_id"),
    )


class InvoiceLineItem(Base):
    """A single line on an invoice — maps to an order item."""
    __tablename__ = "invoice_line_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id = Column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_item_id = Column(UUID(as_uuid=True), ForeignKey("order_items.id"), nullable=True)

    sku = Column(String(100), nullable=False)
    description = Column(String(500), nullable=False)
    quantity = Column(Numeric(10, 3), nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)
    discount_amount = Column(Numeric(12, 2), nullable=False, default=0)
    tax_amount = Column(Numeric(12, 2), nullable=False, default=0)
    line_total = Column(Numeric(12, 2), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    invoice = relationship("Invoice", back_populates="line_items")


class InvoicePayment(Base):
    """A partial or full payment recorded against an invoice."""
    __tablename__ = "invoice_payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id = Column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    amount = Column(Numeric(12, 2), nullable=False)
    payment_date = Column(Date, nullable=False)
    payment_method = Column(SAEnum(PaymentMethod), nullable=False)
    reference_number = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    recorded_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    invoice = relationship("Invoice", back_populates="payments")


class CreditMemo(Base):
    """Credit note / credit memo — reduces a customer's outstanding balance."""
    __tablename__ = "credit_memos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    memo_number = Column(String(50), unique=True, nullable=False, index=True)

    customer_account_id = Column(
        UUID(as_uuid=True), ForeignKey("customer_accounts.id"), nullable=False, index=True
    )
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=True, index=True)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)

    status = Column(SAEnum(CreditMemoStatus), default=CreditMemoStatus.DRAFT, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    reason = Column(String(500), nullable=False)
    notes = Column(Text, nullable=True)

    issued_date = Column(Date, nullable=True)
    applied_date = Column(Date, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    customer_account = relationship("CustomerAccount", lazy="select")
    invoice = relationship("Invoice", lazy="select")
