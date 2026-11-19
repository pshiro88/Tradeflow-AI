import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.core.constants import SUPPORTED_CURRENCIES
from app.models.enums import AllocationType, InvoiceStatus

# Positive money with at most 2 decimal places. Serialised to JSON as a string (never a float).
Money = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=2)]
TrimmedStr = Annotated[str, StringConstraints(strip_whitespace=True)]


class InvoiceBase(BaseModel):
    invoice_number: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    exporter_id: uuid.UUID
    buyer_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    buyer_country: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    invoice_date: date
    due_date: date
    currency: str
    total_amount: Money
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None
    payment_terms: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None = None

    @field_validator("currency")
    @classmethod
    def _currency_supported(cls, value: str) -> str:
        code = value.strip().upper()
        if code not in SUPPORTED_CURRENCIES:
            raise ValueError(f"Unsupported currency. Supported: {', '.join(SUPPORTED_CURRENCIES)}")
        return code

    @model_validator(mode="after")
    def _due_not_before_invoice_date(self) -> Self:
        if self.due_date < self.invoice_date:
            raise ValueError("Due date cannot be before the invoice date")
        return self


class InvoiceCreate(InvoiceBase):
    """New invoice. Starts as a DRAFT or goes straight to OPEN."""

    status: Literal[InvoiceStatus.DRAFT, InvoiceStatus.OPEN] = InvoiceStatus.OPEN


class InvoiceUpdate(InvoiceBase):
    """Full replacement of the editable fields (PUT). Status is changed through the status endpoint."""


class InvoiceStatusUpdate(BaseModel):
    """Manual status transitions. PAID / PARTIALLY_PAID / OVERDUE are derived and cannot be set."""

    status: Literal[InvoiceStatus.OPEN, InvoiceStatus.CANCELLED]


class InvoiceListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_number: str
    buyer_name: str
    buyer_country: str
    exporter_name: str
    invoice_date: date
    due_date: date
    currency: str
    total_amount: Decimal
    amount_received: Decimal
    outstanding_amount: Decimal
    status: InvoiceStatus


class InvoicePaymentOut(BaseModel):
    """One payment allocation applied to the invoice."""

    id: uuid.UUID
    payment_id: uuid.UUID
    transaction_reference: str
    sender_name: str
    transaction_date: date
    allocated_amount: Decimal
    currency: str
    allocation_type: AllocationType
    created_at: datetime


class InvoiceDetail(InvoiceListItem):
    exporter_id: uuid.UUID
    buyer_id: uuid.UUID
    description: str | None
    payment_terms: str | None
    created_at: datetime
    updated_at: datetime
    payments: list[InvoicePaymentOut]
    has_payments: bool
    is_editable: bool


class PartyOut(BaseModel):
    id: uuid.UUID
    name: str
    country: str


class InvoiceFilters(BaseModel):
    """Query filters for the invoice list."""

    search: str | None = None
    status: InvoiceStatus | None = None
    currency: str | None = None
    buyer_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
