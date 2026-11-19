import uuid
from datetime import date
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, model_validator

from app.models.enums import InvoiceStatus, ReconciliationStatus


class DashboardFilters(BaseModel):
    """Dashboard filters (BRD FR-005).

    - date range: invoices by invoice date, payments by transaction date
    - currency: both
    - status: a payment (reconciliation) status; narrows payment-based metrics only
    - buyer: invoices of that buyer, and payments allocated to those invoices
    """

    date_from: date | None = None
    date_to: date | None = None
    currency: str | None = None
    status: ReconciliationStatus | None = None
    buyer_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _range_is_ordered(self) -> Self:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from cannot be after date_to")
        return self


class CurrencyAmount(BaseModel):
    """Money is always reported per currency. Different currencies are never added together."""

    currency: str
    amount: Decimal


class DashboardSummary(BaseModel):
    total_invoices: int  # issued invoices: drafts and cancelled invoices are excluded
    total_invoice_value: list[CurrencyAmount]
    payments_received: list[CurrencyAmount]  # bank receipts, duplicates excluded
    unallocated_received: list[CurrencyAmount]  # received but not yet applied to an invoice
    pending_amount: list[CurrencyAmount]  # outstanding balance on issued invoices
    fully_reconciled_invoices: int
    partially_paid_invoices: int
    unmatched_transactions: int
    overdue_invoices: int


class TrendPoint(BaseModel):
    month: str  # YYYY-MM
    invoiced: Decimal
    received: Decimal


class PaymentTrends(BaseModel):
    currency: str
    available_currencies: list[str]
    points: list[TrendPoint]


class StatusCount(BaseModel):
    status: ReconciliationStatus
    count: int


class PaymentDistribution(BaseModel):
    total: int
    items: list[StatusCount]


class CurrencyShare(BaseModel):
    currency: str
    invoices: int
    payments: int
    invoice_value: Decimal
    received: Decimal


class CurrencyDistribution(BaseModel):
    items: list[CurrencyShare]


class RecentTransaction(BaseModel):
    id: uuid.UUID
    transaction_reference: str
    sender_name: str
    buyer_name: str | None  # the buyer of the invoice it was applied to, if any
    invoice_number: str | None
    currency: str
    amount: Decimal
    transaction_date: date
    status: ReconciliationStatus


class OutstandingInvoice(BaseModel):
    id: uuid.UUID
    invoice_number: str
    buyer_name: str
    currency: str
    due_date: date
    outstanding_amount: Decimal
    status: InvoiceStatus
    days_overdue: int  # negative = days until due
