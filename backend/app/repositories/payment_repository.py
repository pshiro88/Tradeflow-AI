import uuid
from decimal import Decimal
from typing import Literal

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.money import to_money
from app.models.invoice import Invoice
from app.models.payment import ImportBatch, Payment, PaymentAllocation
from app.schemas.payment import PaymentFilters
from app.services.payment_import import ValidRow

SortField = Literal["transaction_date", "created_at", "amount", "transaction_reference", "sender_name"]
SortDir = Literal["asc", "desc"]

INSERT_CHUNK = 1000


class PaymentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def allocated_expression() -> ColumnElement[Decimal]:
        return (
            select(func.coalesce(func.sum(PaymentAllocation.allocated_amount), 0))
            .where(PaymentAllocation.payment_id == Payment.id)
            .correlate(Payment)
            .scalar_subquery()
        )

    # ------------------------------------------------------------------ payments

    @staticmethod
    def _apply_filters(stmt: Select, f: PaymentFilters) -> Select:
        if f.search:
            term = f"%{f.search.strip()}%"
            stmt = stmt.where(
                or_(
                    Payment.transaction_reference.ilike(term),
                    Payment.payment_reference.ilike(term),
                    Payment.sender_name.ilike(term),
                )
            )
        if f.sender:
            stmt = stmt.where(Payment.sender_name.ilike(f"%{f.sender.strip()}%"))
        if f.transaction_reference:
            stmt = stmt.where(Payment.transaction_reference.ilike(f"%{f.transaction_reference.strip()}%"))
        if f.currency:
            stmt = stmt.where(Payment.currency == f.currency.upper())
        if f.status:
            stmt = stmt.where(Payment.status == f.status)
        if f.date_from:
            stmt = stmt.where(Payment.transaction_date >= f.date_from)
        if f.date_to:
            stmt = stmt.where(Payment.transaction_date <= f.date_to)
        if f.import_batch_id:
            stmt = stmt.where(Payment.import_batch_id == f.import_batch_id)
        return stmt

    def list_page(
        self, filters: PaymentFilters, *, page: int, page_size: int, sort_by: SortField, sort_dir: SortDir
    ) -> tuple[list[tuple[Payment, Decimal]], int]:
        total = (
            self.db.scalar(
                select(func.count()).select_from(self._apply_filters(select(Payment.id), filters).subquery())
            )
            or 0
        )
        column = getattr(Payment, sort_by)
        order = column.asc() if sort_dir == "asc" else column.desc()
        stmt = (
            self._apply_filters(select(Payment, self.allocated_expression().label("allocated")), filters)
            .order_by(order, Payment.transaction_reference)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return [(p, to_money(a)) for p, a in self.db.execute(stmt).all()], total

    def get_with_allocated(self, payment_id: uuid.UUID) -> tuple[Payment, Decimal] | None:
        row = self.db.execute(
            select(Payment, self.allocated_expression().label("allocated")).where(Payment.id == payment_id)
        ).first()
        return (row[0], to_money(row[1])) if row else None

    def allocations_for(self, payment_id: uuid.UUID) -> list[tuple[PaymentAllocation, str]]:
        stmt = (
            select(PaymentAllocation, Invoice.invoice_number)
            .join(Invoice, Invoice.id == PaymentAllocation.invoice_id)
            .where(PaymentAllocation.payment_id == payment_id)
            .order_by(PaymentAllocation.created_at)
        )
        return [(a, number) for a, number in self.db.execute(stmt).all()]

    # ------------------------------------------------------------------ import support

    def existing_references(self, references: list[str]) -> set[str]:
        found: set[str] = set()
        for i in range(0, len(references), INSERT_CHUNK):
            chunk = references[i : i + INSERT_CHUNK]
            found.update(self.db.scalars(select(Payment.transaction_reference).where(Payment.transaction_reference.in_(chunk))))
        return found

    def bulk_insert(self, rows: list[ValidRow], batch_id: uuid.UUID) -> set[str]:
        """Insert payments, silently skipping any transaction_reference that already exists.

        `ON CONFLICT DO NOTHING` makes this safe even if another import inserts the same reference
        between our duplicate pre-check and this statement. Returns the references actually inserted.
        """
        inserted: set[str] = set()
        for i in range(0, len(rows), INSERT_CHUNK):
            values = [
                {
                    "id": uuid.uuid4(),
                    "transaction_reference": r.transaction_reference,
                    "payment_reference": r.payment_reference,
                    "sender_name": r.sender_name,
                    "currency": r.currency,
                    "amount": r.amount,
                    "transaction_date": r.transaction_date,
                    "bank_reference": r.bank_reference,
                    "import_batch_id": batch_id,
                    "status": "PENDING",
                }
                for r in rows[i : i + INSERT_CHUNK]
            ]
            stmt = (
                pg_insert(Payment)
                .values(values)
                .on_conflict_do_nothing(index_elements=[Payment.transaction_reference])
                .returning(Payment.transaction_reference)
            )
            inserted.update(self.db.scalars(stmt))
        return inserted

    # ------------------------------------------------------------------ batches

    def add_batch(self, batch: ImportBatch) -> ImportBatch:
        self.db.add(batch)
        self.db.flush()
        return batch

    def get_batch(self, batch_id: uuid.UUID) -> ImportBatch | None:
        return self.db.get(ImportBatch, batch_id)

    def recent_batches(self, limit: int) -> list[ImportBatch]:
        return list(self.db.scalars(select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(limit)))

    def batch_file_name(self, batch_id: uuid.UUID | None) -> str | None:
        if batch_id is None:
            return None
        return self.db.scalar(select(ImportBatch.file_name).where(ImportBatch.id == batch_id))

