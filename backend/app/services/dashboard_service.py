from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.constants import SUPPORTED_CURRENCIES
from app.core.errors import BusinessValidationError
from app.core.money import to_money
from app.models.enums import InvoiceStatus, ReconciliationStatus
from app.repositories.dashboard_repository import DashboardRepository
from app.schemas.dashboard import (
    CurrencyAmount,
    CurrencyDistribution,
    CurrencyShare,
    DashboardFilters,
    DashboardSummary,
    OutstandingInvoice,
    PaymentDistribution,
    PaymentTrends,
    RecentTransaction,
    StatusCount,
    TrendPoint,
)

ZERO = Decimal("0.00")
MAX_TREND_MONTHS = 24


def _currency_order(code: str) -> tuple[int, str]:
    """Stable, human-friendly ordering: supported currencies first in their usual order."""
    return (SUPPORTED_CURRENCIES.index(code) if code in SUPPORTED_CURRENCIES else len(SUPPORTED_CURRENCIES), code)


def _amounts(by_currency: dict[str, Decimal]) -> list[CurrencyAmount]:
    return [CurrencyAmount(currency=c, amount=by_currency[c]) for c in sorted(by_currency, key=_currency_order)]


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _add_months(first_of_month: date, months: int) -> date:
    index = first_of_month.year * 12 + (first_of_month.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def _last_of_month(d: date) -> date:
    return _add_months(_first_of_month(d), 1) - timedelta(days=1)


class DashboardService:
    def __init__(self, db: Session, today: date | None = None) -> None:
        self.today = today or date.today()
        self.repo = DashboardRepository(db, self.today)

    def summary(self, f: DashboardFilters) -> DashboardSummary:
        rows = self.repo.summary(f)
        return DashboardSummary(
            total_invoices=rows.invoice_count,
            total_invoice_value=_amounts(rows.invoice_value),
            payments_received=_amounts(rows.received),
            unallocated_received=_amounts(rows.unallocated),
            pending_amount=_amounts(rows.pending),
            fully_reconciled_invoices=rows.paid,
            partially_paid_invoices=rows.partially_paid,
            unmatched_transactions=rows.unmatched,
            overdue_invoices=rows.overdue,
        )

    def payment_trends(self, f: DashboardFilters, months: int = 6) -> PaymentTrends:
        """Invoiced vs received per month in ONE currency (amounts in different currencies cannot be compared)."""
        # Which currencies can be chosen must not depend on the one currently chosen.
        distribution = self.repo.currency_distribution(f.model_copy(update={"currency": None}))
        available = sorted(distribution, key=_currency_order)
        currency = f.currency.upper() if f.currency else self._primary_currency(f)
        if currency not in SUPPORTED_CURRENCIES:
            raise BusinessValidationError(f"Unsupported currency '{currency}'")

        end_month = _first_of_month(f.date_to or self.today)
        start_month = _first_of_month(f.date_from) if f.date_from else _add_months(end_month, -(months - 1))
        if (end_month.year - start_month.year) * 12 + end_month.month - start_month.month + 1 > MAX_TREND_MONTHS:
            start_month = _add_months(end_month, -(MAX_TREND_MONTHS - 1))

        range_start = max(f.date_from, start_month) if f.date_from else start_month
        range_end = f.date_to or _last_of_month(end_month)
        invoiced, received = self.repo.monthly_totals(f, currency, range_start, range_end)

        points: list[TrendPoint] = []
        month = start_month
        while month <= end_month:
            key = month.strftime("%Y-%m")
            points.append(TrendPoint(month=key, invoiced=invoiced.get(key, ZERO), received=received.get(key, ZERO)))
            month = _add_months(month, 1)
        return PaymentTrends(currency=currency, available_currencies=available, points=points)

    def _primary_currency(self, f: DashboardFilters) -> str:
        """The currency with the most invoices in scope (ties broken by the usual currency order)."""
        counts = self.repo.invoice_currency_counts(f)
        if not counts:
            return SUPPORTED_CURRENCIES[0]
        return min(counts, key=lambda c: (-counts[c], _currency_order(c)))

    def payment_distribution(self, f: DashboardFilters) -> PaymentDistribution:
        counts = self.repo.payment_status_counts(f)
        items = [StatusCount(status=s, count=counts.get(s, 0)) for s in ReconciliationStatus]
        return PaymentDistribution(total=sum(counts.values()), items=items)

    def currency_distribution(self, f: DashboardFilters) -> CurrencyDistribution:
        shares = self.repo.currency_distribution(f)
        return CurrencyDistribution(
            items=[
                CurrencyShare(
                    currency=c,
                    invoices=int(shares[c]["invoices"]),
                    payments=int(shares[c]["payments"]),
                    invoice_value=Decimal(shares[c]["invoice_value"]),
                    received=Decimal(shares[c]["received"]),
                )
                for c in sorted(shares, key=_currency_order)
            ]
        )

    def recent_transactions(self, f: DashboardFilters, limit: int) -> list[RecentTransaction]:
        return [
            RecentTransaction(
                id=p.id,
                transaction_reference=p.transaction_reference,
                sender_name=p.sender_name,
                buyer_name=buyer,
                invoice_number=number,
                currency=p.currency,
                amount=p.amount,
                transaction_date=p.transaction_date,
                status=p.status,
            )
            for p, number, buyer in self.repo.recent_transactions(f, limit)
        ]

    def outstanding_invoices(self, f: DashboardFilters, limit: int) -> list[OutstandingInvoice]:
        return [
            OutstandingInvoice(
                id=invoice_id,
                invoice_number=number,
                buyer_name=buyer,
                currency=currency,
                due_date=due,
                outstanding_amount=to_money(outstanding),
                status=InvoiceStatus(status),
                days_overdue=(self.today - due).days,
            )
            for invoice_id, number, buyer, currency, due, outstanding, status in self.repo.outstanding_invoices(f, limit)
        ]
