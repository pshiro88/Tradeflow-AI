import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin, enum_type
from app.models.enums import AllocationType, ReconciliationStatus, ReviewDecision


class ImportBatch(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One uploaded payment CSV file and its outcome summary."""

    __tablename__ = "import_batches"

    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    accepted_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors: Mapped[list | None] = mapped_column(JSONB)  # per-row rejection reasons
    imported_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class Payment(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_payments_amount_positive"),)

    # Unique constraint is what makes re-importing the same file idempotent.
    transaction_reference: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    payment_reference: Mapped[str | None] = mapped_column(String(100), index=True)
    sender_name: Mapped[str] = mapped_column(String(255), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    bank_reference: Mapped[str | None] = mapped_column(String(100))
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("import_batches.id"))
    status: Mapped[ReconciliationStatus] = mapped_column(
        enum_type(ReconciliationStatus, "reconciliation_status"),
        nullable=False,
        default=ReconciliationStatus.PENDING,
        index=True,
    )


class PaymentAllocation(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Portion of a payment applied to an invoice. Append-only: never overwritten."""

    __tablename__ = "payment_allocations"
    __table_args__ = (CheckConstraint("allocated_amount > 0", name="ck_allocations_amount_positive"),)

    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id"), nullable=False, index=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), nullable=False, index=True)
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    allocation_type: Mapped[AllocationType] = mapped_column(enum_type(AllocationType, "allocation_type"), nullable=False)
    allocated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class ReconciliationResult(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Outcome of one reconciliation attempt for a payment (added to the BRD schema; the API needs it)."""

    __tablename__ = "reconciliation_results"
    # One current result per payment. History lives in the append-only allocations and the audit log.
    __table_args__ = (UniqueConstraint("payment_id", name="uq_reconciliation_results_payment_id"),)

    payment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payments.id"), nullable=False, index=True)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoices.id"), index=True)
    status: Mapped[ReconciliationStatus] = mapped_column(
        enum_type(ReconciliationStatus, "reconciliation_status"), nullable=False
    )
    match_method: Mapped[str | None] = mapped_column(String(50))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    invoice_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    previously_received: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    outstanding_after: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    allocated_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0.00"), server_default="0"
    )
    explanation: Mapped[str | None] = mapped_column(Text)
    # Potential invoices shown to a human reviewer: [{invoice_id, invoice_number, buyer_name, ...}]
    candidates: Mapped[list | None] = mapped_column(JSONB)
    review_note: Mapped[str | None] = mapped_column(Text)
    review_decision: Mapped[ReviewDecision] = mapped_column(
        enum_type(ReviewDecision, "review_decision"), nullable=False, default=ReviewDecision.NONE
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    payment: Mapped[Payment] = relationship()
