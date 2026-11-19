import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy import ColumnElement, Select, String, case, cast, func, or_, select
from sqlalchemy.orm import Session, contains_eager, joinedload

from app.core.money import to_money
from app.models.enums import InvoiceStatus
from app.models.invoice import Invoice
from app.models.party import Buyer, Exporter
from app.models.payment import Payment, PaymentAllocation
from app.schemas.invoice import InvoiceFilters

SortField = Literal["invoice_date", "due_date", "total_amount", "invoice_number", "outstanding_amount"]
SortDir = Literal["asc", "desc"]


class InvoiceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ SQL expressions

    @staticmethod
    def received_expression() -> ColumnElement[Decimal]:
        """Total allocated to the invoice, computed from payment_allocations (correlated subquery)."""
        return (
            select(func.coalesce(func.sum(PaymentAllocation.allocated_amount), 0))
            .where(PaymentAllocation.invoice_id == Invoice.id)
            .correlate(Invoice)
            .scalar_subquery()
        )

    @classmethod
    def status_expression(cls, today: date) -> ColumnElement[str]:
        """SQL mirror of `invoice_status.derive_status`."""
        received = cls.received_expression()
        stored = cast(Invoice.status, String)
        return case(
            (stored.in_([InvoiceStatus.DRAFT.value, InvoiceStatus.CANCELLED.value]), stored),
            (received >= Invoice.total_amount, InvoiceStatus.PAID.value),
            (Invoice.due_date < today, InvoiceStatus.OVERDUE.value),
            (received > 0, InvoiceStatus.PARTIALLY_PAID.value),
            else_=InvoiceStatus.OPEN.value,
        )

    # ------------------------------------------------------------------ queries

    def _apply_filters(self, stmt: Select, filters: InvoiceFilters, today: date) -> Select:
        if filters.search:
            term = f"%{filters.search.strip()}%"
            stmt = stmt.where(or_(Invoice.invoice_number.ilike(term), Buyer.buyer_name.ilike(term)))
        if filters.status:
            stmt = stmt.where(self.status_expression(today) == filters.status.value)
        if filters.currency:
            stmt = stmt.where(Invoice.currency == filters.currency.upper())
        if filters.buyer_id:
            stmt = stmt.where(Invoice.buyer_id == filters.buyer_id)
        if filters.date_from:
            stmt = stmt.where(Invoice.invoice_date >= filters.date_from)
        if filters.date_to:
            stmt = stmt.where(Invoice.invoice_date <= filters.date_to)
        return stmt

    def list_page(
        self,
        filters: InvoiceFilters,
        *,
        today: date,
        page: int,
        page_size: int,
        sort_by: SortField,
        sort_dir: SortDir,
    ) -> tuple[list[tuple[Invoice, Decimal, str]], int]:
        """Return ([(invoice, amount_received, effective_status)], total_matching)."""
        received = self.received_expression().label("amount_received")
        status = self.status_expression(today).label("effective_status")

        base_ids = self._apply_filters(select(Invoice.id).join(Invoice.buyer), filters, today)
        total = self.db.scalar(select(func.count()).select_from(base_ids.subquery())) or 0

        sort_columns: dict[str, ColumnElement] = {
            "invoice_date": Invoice.invoice_date,
            "due_date": Invoice.due_date,
            "total_amount": Invoice.total_amount,
            "invoice_number": Invoice.invoice_number,
            "outstanding_amount": Invoice.total_amount - self.received_expression(),
        }
        order = sort_columns[sort_by]
        order = order.asc() if sort_dir == "asc" else order.desc()

        stmt = (
            self._apply_filters(select(Invoice, received, status).join(Invoice.buyer), filters, today)
            .options(contains_eager(Invoice.buyer), joinedload(Invoice.exporter))
            .order_by(order, Invoice.invoice_number)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = [(inv, to_money(rec), st) for inv, rec, st in self.db.execute(stmt).unique().all()]
        return rows, total

    def get_with_totals(self, invoice_id: uuid.UUID, today: date) -> tuple[Invoice, Decimal, str] | None:
        stmt = select(
            Invoice, self.received_expression().label("r"), self.status_expression(today).label("s")
        ).where(Invoice.id == invoice_id)
        row = self.db.execute(stmt).unique().first()
        if row is None:
            return None
        return row[0], to_money(row[1]), row[2]

    def get(self, invoice_id: uuid.UUID, *, for_update: bool = False) -> Invoice | None:
        stmt = select(Invoice).where(Invoice.id == invoice_id)
        if for_update:
            # Lock only the invoice row (not the eagerly joined parties) to serialise concurrent edits.
            stmt = stmt.with_for_update(of=Invoice)
        return self.db.execute(stmt).unique().scalar_one_or_none()

    def find_by_number(self, invoice_number: str) -> Invoice | None:
        stmt = select(Invoice).where(func.lower(Invoice.invoice_number) == invoice_number.strip().lower())
        return self.db.execute(stmt).unique().scalar_one_or_none()

    def number_exists(self, invoice_number: str, *, exclude_id: uuid.UUID | None = None) -> bool:
        stmt = select(Invoice.id).where(func.lower(Invoice.invoice_number) == invoice_number.lower())
        if exclude_id:
            stmt = stmt.where(Invoice.id != exclude_id)
        return self.db.scalar(stmt.limit(1)) is not None

    def received_total(self, invoice_id: uuid.UUID) -> Decimal:
        value = self.db.scalar(
            select(func.coalesce(func.sum(PaymentAllocation.allocated_amount), 0)).where(
                PaymentAllocation.invoice_id == invoice_id
            )
        )
        return to_money(value)

    def payments_for(self, invoice_id: uuid.UUID) -> list[tuple[PaymentAllocation, Payment]]:
        stmt = (
            select(PaymentAllocation, Payment)
            .join(Payment, Payment.id == PaymentAllocation.payment_id)
            .where(PaymentAllocation.invoice_id == invoice_id)
            .order_by(Payment.transaction_date, PaymentAllocation.created_at)
        )
        return [(a, p) for a, p in self.db.execute(stmt).all()]

    def add(self, invoice: Invoice) -> Invoice:
        self.db.add(invoice)
        self.db.flush()
        return invoice

    # ------------------------------------------------------------------ parties

    def list_exporters(self) -> list[Exporter]:
        return list(self.db.scalars(select(Exporter).order_by(Exporter.company_name)))

    def list_buyers(self) -> list[Buyer]:
        return list(self.db.scalars(select(Buyer).order_by(Buyer.buyer_name)))

    def get_exporter(self, exporter_id: uuid.UUID) -> Exporter | None:
        return self.db.get(Exporter, exporter_id)

    def find_buyer_by_name(self, name: str) -> Buyer | None:
        return self.db.scalar(select(Buyer).where(func.lower(Buyer.buyer_name) == name.lower()).limit(1))

    def add_buyer(self, buyer: Buyer) -> Buyer:
        self.db.add(buyer)
        self.db.flush()
        return buyer

