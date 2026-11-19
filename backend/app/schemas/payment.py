import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models.enums import AllocationType, ReconciliationStatus

ImportErrorCategory = Literal["VALIDATION", "DUPLICATE_IN_FILE", "DUPLICATE_EXISTING"]


class PaymentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    transaction_reference: str
    payment_reference: str | None
    sender_name: str
    currency: str
    amount: Decimal
    allocated_amount: Decimal
    transaction_date: date
    created_at: datetime  # when it was imported (UTC)
    status: ReconciliationStatus
    import_batch_id: uuid.UUID | None


class PaymentAllocationOut(BaseModel):
    id: uuid.UUID
    invoice_id: uuid.UUID
    invoice_number: str
    allocated_amount: Decimal
    currency: str
    allocation_type: AllocationType
    created_at: datetime


class PaymentDetail(PaymentListItem):
    bank_reference: str | None
    import_file_name: str | None
    allocations: list[PaymentAllocationOut]


class PaymentFilters(BaseModel):
    """Query filters for the payments list (BRD FR-013)."""

    search: str | None = None  # matches transaction ref, payment ref or sender
    sender: str | None = None
    transaction_reference: str | None = None
    currency: str | None = None
    status: ReconciliationStatus | None = None
    date_from: date | None = None
    date_to: date | None = None
    import_batch_id: uuid.UUID | None = None


class ImportIssue(BaseModel):
    field: str
    message: str


class ImportRowError(BaseModel):
    """One row that was not imported, with the reason(s)."""

    row: int
    transaction_reference: str | None
    category: ImportErrorCategory
    issues: list[ImportIssue]
    values: dict[str, str]


class ImportBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    file_name: str
    total_rows: int
    accepted_rows: int
    rejected_rows: int
    duplicate_rows: int
    created_at: datetime


class ImportBatchDetail(ImportBatchOut):
    errors: list[ImportRowError]
