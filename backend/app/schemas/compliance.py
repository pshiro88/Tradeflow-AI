import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

from app.models.enums import DocumentStatus, DocumentType, ExtractionStatus, InvoiceStatus
from app.schemas.document import FindingOut

Remarks = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class ChecklistDocument(BaseModel):
    id: uuid.UUID
    file_name: str
    verification_status: DocumentStatus
    extraction_status: ExtractionStatus


class ChecklistItem(BaseModel):
    document_type: DocumentType
    label: str
    required: bool
    requirement_note: str | None
    status: DocumentStatus
    source: Literal["DOCUMENT", "MANUAL", "NONE"]
    documents: list[ChecklistDocument]
    remarks: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    compared_document: str | None  # the document whose values were compared with the invoice
    findings: list[FindingOut]
    has_mismatch: bool


class ChecklistSummary(BaseModel):
    required_total: int
    verified: int
    under_review: int
    uploaded: int
    rejected: int
    missing: int
    flagged: int
    complete: bool


class Readiness(BaseModel):
    ready: bool
    reasons: list[str]


class Checklist(BaseModel):
    invoice_id: uuid.UUID
    invoice_number: str
    buyer_name: str
    invoice_status: InvoiceStatus
    items: list[ChecklistItem]
    summary: ChecklistSummary
    readiness: Readiness
    disclaimer: str


class CheckRequest(BaseModel):
    """A person's manual review of one checklist item (for example a paper document that was inspected)."""

    document_type: DocumentType
    status: Literal[DocumentStatus.UNDER_REVIEW, DocumentStatus.VERIFIED, DocumentStatus.REJECTED]
    remarks: Remarks | None = None


class OverviewItem(BaseModel):
    invoice_id: uuid.UUID
    invoice_number: str
    buyer_name: str
    currency: str
    invoice_status: InvoiceStatus
    due_date: date
    required_total: int
    verified: int
    missing: int
    flagged: int
    complete: bool
    ready: bool


class OverviewFilters(BaseModel):
    search: str | None = None
    incomplete_only: bool = False


LifecycleState = Literal["DONE", "IN_PROGRESS", "PENDING", "NOT_APPLICABLE"]


class LifecycleStep(BaseModel):
    key: str
    label: str
    state: LifecycleState
    date: date | None
    detail: str


class Lifecycle(BaseModel):
    invoice_id: uuid.UUID
    steps: list[LifecycleStep]
    readiness: Readiness
    note: str
