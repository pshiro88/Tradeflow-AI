"""Aggregate queries for the dashboard. Every figure comes from the database; nothing is hardcoded.

Invoice-based figures reuse `InvoiceRepository.status_expression` / `received_expression`, so the
dashboard can never disagree with the Invoices page about what is paid, partly paid or overdue.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import ColumnElement, and_, case, exists, func, select
from sqlalchemy.orm import Session

from app.core.money import to_money
from app.models.enums import InvoiceStatus, ReconciliationStatus
from app.models.invoice import Invoice
from app.models.party import Buyer
from app.models.payment import Payment, PaymentAllocation, ReconciliationResult
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.payment_repository import PaymentRepository
from app.schemas.dashboard import DashboardFilters

ISSUED_EXCLUDED = (InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED)
ZERO = Decimal("0.00")


@dataclass
class SummaryRows:
    invoice_count: int = 0
    paid: int = 0
    partially_paid: int = 0
    overdue: int = 0
    invoice_value: dict[str, Decimal] = field(default_factory=dict)
    pending: dict[str, Decimal] = field(default_factory=dict)
    received: dict[str, Decimal] = field(default_factory=dict)
    unallocated: dict[str, Decimal] = field(default_factory=dict)
    unmatched: int = 0


class DashboardRepository:
    def __init__(self, db: Session, today: date) -> None:
        self.db = db
        self.today = today

    # ------------------------------------------------------------------ filter conditions

    @staticmethod
    def invoice_conditions(f: DashboardFilters, *, include_dates: bool = True) -> list[ColumnElement[bool]]:
        conds: list[ColumnElement[bool]] = [Invoice.status.notin_(ISSUED_EXCLUDED)]
        if include_dates and f.date_from:
            conds.append(Invoice.invoice_date >= f.date_from)
        if include_dates and f.date_to:
            conds.append(Invoice.invoice_date <= f.date_to)
        if f.currency:
            conds.append(Invoice.currency == f.currency.upper())
        if f.buyer_id:
            conds.append(Invoice.buyer_id == f.buyer_id)
        return conds

    @staticmethod
    def payment_conditions(
        f: DashboardFilters, *, include_dates: bool = True, include_status: bool = True
    ) -> list[ColumnElement[bool]]:
        conds: list[ColumnElement[bool]] = []
        if include_dates and f.date_from:
            conds.append(Payment.transaction_date >= f.date_from)
        if include_dates and f.date_to:
            conds.append(Payment.transaction_date <= f.date_to)
        if f.currency:
            conds.append(Payment.currency == f.currency.upper())
        if include_status and f.status:
            conds.append(Payment.status == f.status)
        if f.buyer_id:
            # Payments carry no buyer of their own: match those applied to this buyer's invoices.
            conds.append(
                exists(
                    select(1)
                    .select_from(PaymentAllocation)
                    .join(Invoice, Invoice.id == PaymentAllocation.invoice_id)
                    .where(PaymentAllocation.payment_id == Payment.id, Invoice.buyer_id == f.buyer_id)
                )
            )
        return conds

    # ------------------------------------------------------------------ KPI summary

    def summary(self, f: DashboardFilters) -> SummaryRows:
        out = SummaryRows()

        inv = (
            select(
                Invoice.currency.label("currency"),
                Invoice.total_amount.label("total"),
                InvoiceRepository.received_expression().label("received"),
                InvoiceRepository.status_expression(self.today).label("status"),
            )
            .where(*self.invoice_conditions(f))
            .subquery()
        )
        outstanding = case((inv.c.total > inv.c.received, inv.c.total - inv.c.received), else_=0)
        rows = self.db.execute(
            select(
                inv.c.currency,
                func.count(),
                func.sum(inv.c.total),
                func.sum(outstanding),
                func.count().filter(inv.c.status == InvoiceStatus.PAID.value),
                func.count().filter(inv.c.received > 0, inv.c.total > inv.c.received),
                func.count().filter(inv.c.status == InvoiceStatus.OVERDUE.value),
            ).group_by(inv.c.currency)
        ).all()
        for currency, count, total, pending, paid, partial, overdue in rows:
            out.invoice_count += count
            out.invoice_value[currency] = to_money(total)
            out.pending[currency] = to_money(pending)
            out.paid += paid
            out.partially_paid += partial
            out.overdue += overdue

        pay = (
            select(
                Payment.currency.label("currency"),
                Payment.amount.label("amount"),
                Payment.status.label("status"),
                PaymentRepository.allocated_expression().label("allocated"),
            )
            .where(*self.payment_conditions(f))
            .subquery()
        )
        real = pay.c.status != ReconciliationStatus.DUPLICATE  # a bank duplicate is not a second receipt
        rows = self.db.execute(
            select(
                pay.c.currency,
                func.coalesce(func.sum(pay.c.amount).filter(real), 0),
                func.coalesce(func.sum(pay.c.amount - pay.c.allocated).filter(real), 0),
                func.count().filter(pay.c.status == ReconciliationStatus.UNMATCHED),
            ).group_by(pay.c.currency)
        ).all()
        for currency, received, unallocated, unmatched in rows:
            if received:
                out.received[currency] = to_money(received)
            if unallocated:
                out.unallocated[currency] = to_money(unallocated)
            out.unmatched += unmatched
        return out

    # ------------------------------------------------------------------ trends

    def invoice_currency_counts(self, f: DashboardFilters) -> dict[str, int]:
        rows = self.db.execute(
            select(Invoice.currency, func.count()).where(*self.invoice_conditions(f)).group_by(Invoice.currency)
        ).all()
        return {currency: count for currency, count in rows}

    def monthly_totals(
        self, f: DashboardFilters, currency: str, start: date, end: date
    ) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
        """(invoiced, received) by 'YYYY-MM' for one currency within [start, end]."""
        invoiced_month = func.to_char(Invoice.invoice_date, "YYYY-MM")
        invoiced = {
            month: to_money(total)
            for month, total in self.db.execute(
                select(invoiced_month, func.sum(Invoice.total_amount))
                .where(
                    *self.invoice_conditions(f, include_dates=False),
                    Invoice.currency == currency,
                    Invoice.invoice_date >= start,
                    Invoice.invoice_date <= end,
                )
                .group_by(invoiced_month)
            ).all()
        }
        received_month = func.to_char(Payment.transaction_date, "YYYY-MM")
        received = {
            month: to_money(total)
            for month, total in self.db.execute(
                select(received_month, func.sum(Payment.amount))
                .where(
                    *self.payment_conditions(f, include_dates=False),
                    Payment.currency == currency,
                    Payment.status != ReconciliationStatus.DUPLICATE,
                    Payment.transaction_date >= start,
                    Payment.transaction_date <= end,
                )
                .group_by(received_month)
            ).all()
        }
        return invoiced, received

    # ------------------------------------------------------------------ distributions

    def payment_status_counts(self, f: DashboardFilters) -> dict[ReconciliationStatus, int]:
        # The status filter is ignored here: a chart of statuses filtered to one status would be pointless.
        rows = self.db.execute(
            select(Payment.status, func.count())
            .where(*self.payment_conditions(f, include_status=False))
            .group_by(Payment.status)
        ).all()
        return {status: count for status, count in rows}

    def currency_distribution(self, f: DashboardFilters) -> dict[str, dict[str, Decimal | int]]:
        shares: dict[str, dict[str, Decimal | int]] = {}

        def row(currency: str) -> dict[str, Decimal | int]:
            return shares.setdefault(currency, {"invoices": 0, "payments": 0, "invoice_value": ZERO, "received": ZERO})

        for currency, count, total in self.db.execute(
            select(Invoice.currency, func.count(), func.sum(Invoice.total_amount))
            .where(*self.invoice_conditions(f))
            .group_by(Invoice.currency)
        ).all():
            entry = row(currency)
            entry["invoices"], entry["invoice_value"] = count, to_money(total)

        for currency, count, total in self.db.execute(
            select(Payment.currency, func.count(), func.sum(Payment.amount))
            .where(*self.payment_conditions(f), Payment.status != ReconciliationStatus.DUPLICATE)
            .group_by(Payment.currency)
        ).all():
            entry = row(currency)
            entry["payments"], entry["received"] = count, to_money(total)
        return shares

    # ------------------------------------------------------------------ widgets

    def recent_transactions(self, f: DashboardFilters, limit: int) -> list[tuple[Payment, str | None, str | None]]:
        """Latest payments with the invoice/buyer they were actually applied to (if any)."""
        stmt = (
            select(Payment, Invoice.invoice_number, Buyer.buyer_name)
            .outerjoin(
                ReconciliationResult,
                and_(ReconciliationResult.payment_id == Payment.id, ReconciliationResult.allocated_amount > 0),
            )
            .outerjoin(Invoice, Invoice.id == ReconciliationResult.invoice_id)
            .outerjoin(Buyer, Buyer.id == Invoice.buyer_id)
            .where(*self.payment_conditions(f))
            .order_by(Payment.transaction_date.desc(), Payment.created_at.desc(), Payment.transaction_reference.desc())
            .limit(limit)
        )
        return [(p, number, buyer) for p, number, buyer in self.db.execute(stmt).all()]

    def outstanding_invoices(self, f: DashboardFilters, limit: int) -> list[tuple]:
        """Issued invoices with a balance, oldest due date first."""
        received = InvoiceRepository.received_expression()
        stmt = (
            select(
                Invoice.id,
                Invoice.invoice_number,
                Buyer.buyer_name,
                Invoice.currency,
                Invoice.due_date,
                (Invoice.total_amount - received).label("outstanding"),
                InvoiceRepository.status_expression(self.today).label("status"),
            )
            .join(Buyer, Buyer.id == Invoice.buyer_id)
            .where(*self.invoice_conditions(f), Invoice.total_amount > received)
            .order_by(Invoice.due_date, Invoice.invoice_number)
            .limit(limit)
        )
        return [tuple(r) for r in self.db.execute(stmt).all()]
