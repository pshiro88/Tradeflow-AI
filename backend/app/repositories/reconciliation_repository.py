import uuid
from decimal import Decimal

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.orm import Session

from app.core.money import to_money
from app.models.enums import InvoiceStatus, ReconciliationStatus
from app.models.invoice import Invoice
from app.models.payment import Payment, PaymentAllocation, ReconciliationResult
from app.models.user import User
from app.schemas.reconciliation import ReconciliationFilters

# Results a person still has to act on (approve an allocation, or reject a suggested one).
NEEDS_ATTENTION = (ReconciliationStatus.MANUAL_REVIEW, ReconciliationStatus.MISMATCH, ReconciliationStatus.UNMATCHED)
PAYABLE_EXCLUDED = (InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED)


class ReconciliationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ run support (locking reads)

    def lock_pending_payments(self) -> list[Payment]:
        """Pending payments in processing order, locked. Rows another run already holds are skipped,
        so two concurrent runs can never process the same payment twice."""
        stmt = (
            select(Payment)
            .where(Payment.status == ReconciliationStatus.PENDING)
            .order_by(Payment.transaction_date, Payment.transaction_reference)
            .with_for_update(skip_locked=True)
        )
        return list(self.db.scalars(stmt))

    def lock_all_invoices(self) -> list[Invoice]:
        # of=Invoice: lock only the invoice rows, not the eagerly-joined buyer / exporter rows.
        return list(self.db.execute(select(Invoice).with_for_update(of=Invoice)).unique().scalars())

    def allocated_by_invoice(self) -> dict[uuid.UUID, Decimal]:
        rows = self.db.execute(
            select(PaymentAllocation.invoice_id, func.sum(PaymentAllocation.allocated_amount)).group_by(
                PaymentAllocation.invoice_id
            )
        ).all()
        return {invoice_id: to_money(total) for invoice_id, total in rows}

    def processed_payments(self) -> list[Payment]:
        """Already-reconciled, non-duplicate payments: the reference set for duplicate detection."""
        stmt = (
            select(Payment)
            .where(Payment.status.notin_([ReconciliationStatus.PENDING, ReconciliationStatus.DUPLICATE]))
            .order_by(Payment.transaction_date, Payment.transaction_reference)
        )
        return list(self.db.scalars(stmt))

    # ------------------------------------------------------------------ single-record reads

    def get_result(self, result_id: uuid.UUID, *, for_update: bool = False) -> ReconciliationResult | None:
        stmt = select(ReconciliationResult).where(ReconciliationResult.id == result_id)
        if for_update:
            stmt = stmt.with_for_update()
        return self.db.scalars(stmt).first()

    def lock_payment(self, payment_id: uuid.UUID) -> Payment:
        return self.db.scalars(select(Payment).where(Payment.id == payment_id).with_for_update()).one()

    def lock_invoice(self, invoice_id: uuid.UUID) -> Invoice | None:
        stmt = select(Invoice).where(Invoice.id == invoice_id).with_for_update(of=Invoice)
        return self.db.execute(stmt).unique().scalar_one_or_none()

    def allocated_for_payment(self, payment_id: uuid.UUID) -> Decimal:
        return to_money(
            self.db.scalar(
                select(func.coalesce(func.sum(PaymentAllocation.allocated_amount), 0)).where(
                    PaymentAllocation.payment_id == payment_id
                )
            )
        )

    def allocated_for_invoice(self, invoice_id: uuid.UUID) -> Decimal:
        return to_money(
            self.db.scalar(
                select(func.coalesce(func.sum(PaymentAllocation.allocated_amount), 0)).where(
                    PaymentAllocation.invoice_id == invoice_id
                )
            )
        )

    def get_invoice_number(self, invoice_id: uuid.UUID | None) -> str | None:
        if invoice_id is None:
            return None
        return self.db.scalar(select(Invoice.invoice_number).where(Invoice.id == invoice_id))

    def reviewer_name(self, user_id: uuid.UUID | None) -> str | None:
        if user_id is None:
            return None
        return self.db.scalar(select(User.full_name).where(User.id == user_id))

    def payable_invoices(self, currency: str) -> list[tuple[Invoice, Decimal]]:
        """Open-for-payment invoices in one currency that still have a balance, with allocated totals."""
        allocated = (
            select(func.coalesce(func.sum(PaymentAllocation.allocated_amount), 0))
            .where(PaymentAllocation.invoice_id == Invoice.id)
            .correlate(Invoice)
            .scalar_subquery()
        )
        stmt = (
            select(Invoice, allocated.label("allocated"))
            .where(Invoice.currency == currency, Invoice.status.notin_(PAYABLE_EXCLUDED), Invoice.total_amount > allocated)
            .order_by(Invoice.due_date)
        )
        return [(inv, to_money(a)) for inv, a in self.db.execute(stmt).unique().all()]

    # ------------------------------------------------------------------ writes

    def add_result(self, result: ReconciliationResult) -> ReconciliationResult:
        self.db.add(result)
        self.db.flush()
        return result

    def add_allocation(self, allocation: PaymentAllocation) -> PaymentAllocation:
        # Flush immediately so the database trigger validates the limits before we continue.
        self.db.add(allocation)
        self.db.flush()
        return allocation

    # ------------------------------------------------------------------ listing

    @staticmethod
    def _apply_filters(stmt: Select, f: ReconciliationFilters) -> Select:
        if f.status:
            stmt = stmt.where(ReconciliationResult.status == f.status)
        if f.needs_review is True:
            stmt = stmt.where(ReconciliationResult.status.in_(NEEDS_ATTENTION))
        if f.search:
            term = f"%{f.search.strip()}%"
            stmt = stmt.where(
                or_(
                    Payment.transaction_reference.ilike(term),
                    Payment.payment_reference.ilike(term),
                    Payment.sender_name.ilike(term),
                    Invoice.invoice_number.ilike(term),
                )
            )
        return stmt

    def list_page(
        self, filters: ReconciliationFilters, *, page: int, page_size: int
    ) -> tuple[list[tuple[ReconciliationResult, Payment, str | None, str | None]], int]:
        base = (
            select(ReconciliationResult.id)
            .join(Payment, Payment.id == ReconciliationResult.payment_id)
            .outerjoin(Invoice, Invoice.id == ReconciliationResult.invoice_id)
        )
        total = self.db.scalar(select(func.count()).select_from(self._apply_filters(base, filters).subquery())) or 0

        order: tuple[ColumnElement, ...] = (Payment.transaction_date.desc(), Payment.transaction_reference.asc())
        stmt = (
            self._apply_filters(
                select(ReconciliationResult, Payment, Invoice.invoice_number, Invoice.currency)
                .join(Payment, Payment.id == ReconciliationResult.payment_id)
                .outerjoin(Invoice, Invoice.id == ReconciliationResult.invoice_id),
                filters,
            )
            .order_by(*order)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return [(r, p, number, cur) for r, p, number, cur in self.db.execute(stmt).all()], total

    def get_row(self, result_id: uuid.UUID) -> tuple[ReconciliationResult, Payment, str | None, str | None] | None:
        stmt = (
            select(ReconciliationResult, Payment, Invoice.invoice_number, Invoice.currency)
            .join(Payment, Payment.id == ReconciliationResult.payment_id)
            .outerjoin(Invoice, Invoice.id == ReconciliationResult.invoice_id)
            .where(ReconciliationResult.id == result_id)
        )
        row = self.db.execute(stmt).first()
        return (row[0], row[1], row[2], row[3]) if row else None

    def status_counts(self) -> dict[str, int]:
        rows = self.db.execute(select(Payment.status, func.count()).group_by(Payment.status)).all()
        return {status.value: count for status, count in rows}
