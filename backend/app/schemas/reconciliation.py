import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.models.enums import ReconciliationStatus, ReviewDecision
from app.schemas.invoice import Money

Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class CandidateOut(BaseModel):
    invoice_id: uuid.UUID
    invoice_number: str
    buyer_name: str
    currency: str
    outstanding: Decimal
    name_score: int
    reason: str


class ReconciliationItem(BaseModel):
    """One reconciliation outcome, with every field required by BRD FR-016."""

    id: uuid.UUID
    payment_id: uuid.UUID
    transaction_reference: str
    payment_reference: str | None
    sender_name: str
    currency: str
    payment_amount: Decimal
    transaction_date: date
    invoice_id: uuid.UUID | None
    invoice_number: str | None
    invoice_currency: str | None  # can differ from `currency` on a MISMATCH
    invoice_amount: Decimal | None
    previously_received: Decimal | None
    allocated_amount: Decimal
    outstanding_after: Decimal | None
    match_method: str | None
    confidence: Decimal | None  # an estimate for reviewers, not a probability
    status: ReconciliationStatus
    explanation: str | None
    review_decision: ReviewDecision
    needs_review: bool
    created_at: datetime


class ReconciliationDetail(ReconciliationItem):
    candidates: list[CandidateOut]
    review_note: str | None
    reviewed_by_name: str | None
    reviewed_at: datetime | None
    payment_unallocated: Decimal


class ReconciliationFilters(BaseModel):
    status: ReconciliationStatus | None = None
    needs_review: bool | None = None
    search: str | None = None  # transaction ref, payment ref, sender or invoice number


class StatusSummary(BaseModel):
    """Counts for the summary cards. Keys are ReconciliationStatus values (PENDING = not yet processed)."""

    counts: dict[str, int]
    total: int
    needs_review: int


class RunSummary(BaseModel):
    processed: int
    counts: dict[str, int]
    allocations_created: int


class ApproveRequest(BaseModel):
    invoice_id: uuid.UUID
    amount: Money | None = Field(default=None, description="Defaults to the largest amount that fits")
    note: Note | None = None


class RejectRequest(BaseModel):
    note: Note | None = None


class EligibleInvoice(BaseModel):
    invoice_id: uuid.UUID
    invoice_number: str
    buyer_name: str
    currency: str
    outstanding: Decimal
    due_date: date
    name_score: int
    is_candidate: bool
