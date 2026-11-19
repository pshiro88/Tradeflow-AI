import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.enums import DocumentStatus, DocumentType, ExtractionStatus
from app.services.document_extraction import ExtractedFields

FieldQuality = Literal["FOUND_IN_TEXT", "NOT_FOUND_IN_TEXT", "INFERRED", "MISSING"]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class FieldIssueOut(BaseModel):
    field: str
    message: str


class ExtractionInfo(BaseModel):
    """What the AI extracted. Values are strings (money and dates are never floats)."""

    fields: dict[str, str | None]
    quality: dict[str, FieldQuality]
    llm_confidence: dict[str, float]  # the model's own estimate, NOT a probability
    issues: list[FieldIssueOut]
    model: str
    truncated: bool
    page_count: int


class ConfirmationInfo(BaseModel):
    fields: dict[str, str | None]
    decision: Literal["VERIFIED", "REJECTED"]
    note: str | None
    by: str | None
    at: datetime | None


class DocumentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_id: uuid.UUID | None
    invoice_number: str | None
    file_name: str
    document_type: DocumentType
    extraction_status: ExtractionStatus
    verification_status: DocumentStatus
    uploaded_by_name: str | None
    created_at: datetime


class DocumentDetail(DocumentListItem):
    extraction: ExtractionInfo | None
    confirmation: ConfirmationInfo | None


class DocumentFilters(BaseModel):
    invoice_id: uuid.UUID | None = None
    document_type: DocumentType | None = None
    extraction_status: ExtractionStatus | None = None
    verification_status: DocumentStatus | None = None
    search: str | None = None


class VerifyRequest(BaseModel):
    """A person's decision. When VERIFIED, `fields` holds the (possibly corrected) values they confirm."""

    decision: Literal["VERIFIED", "REJECTED"]
    fields: ExtractedFields | None = None
    note: Note | None = None


class FindingOut(BaseModel):
    field: str
    label: str
    status: Literal["MATCH", "MISMATCH", "NOT_COMPARABLE"]
    document_value: str | None
    invoice_value: str
    message: str


class DocumentExplanation(BaseModel):
    summary: str
    generated_by: Literal["AI", "RULES"]
    ai_note: str | None = Field(default=None, description="Why the deterministic summary was used, if it was")
    missing_fields: list[str]
    needs_verification: list[str]
    findings: list[FindingOut]
