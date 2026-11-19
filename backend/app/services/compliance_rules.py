"""Trade-documentation checklist rules (BRD module 7, FR-026 .. FR-028).

PURE LOGIC: no database, no AI. This is an OPERATIONAL completeness check ("do we hold the paperwork, and does it agree
with the invoice?"), not a regulatory compliance engine. Nothing here means legal or regulatory approval.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from app.models.enums import DocumentStatus, DocumentType, ExtractionStatus

DISCLAIMER = (
    "This checklist shows whether the documents are on file and agree with the invoice. It is not legal or "
    "regulatory approval, and TradeFlow does not file anything with any authority."
)


@dataclass(frozen=True)
class ChecklistConfig:
    document_type: DocumentType
    label: str
    # ALWAYS: needed for every issued invoice.  AFTER_PAYMENT: needed once any payment has been received.
    requirement: Literal["ALWAYS", "AFTER_PAYMENT"]


# The configurable checklist (FR-026). Change this one list to change what every invoice needs.
CHECKLIST: tuple[ChecklistConfig, ...] = (
    ChecklistConfig(DocumentType.COMMERCIAL_INVOICE, "Commercial Invoice", "ALWAYS"),
    ChecklistConfig(DocumentType.PACKING_LIST, "Packing List", "ALWAYS"),
    ChecklistConfig(DocumentType.SHIPPING_BILL, "Shipping Bill", "ALWAYS"),
    ChecklistConfig(DocumentType.BILL_OF_LADING, "Bill of Lading / Airway Bill", "ALWAYS"),
    ChecklistConfig(DocumentType.REMITTANCE_ADVICE, "Remittance Advice", "AFTER_PAYMENT"),
)
ALWAYS_REQUIRED = tuple(c.document_type for c in CHECKLIST if c.requirement == "ALWAYS")

# Status precedence when only documents are considered: the most advanced one represents the item.
_PRECEDENCE = {
    DocumentStatus.VERIFIED: 4,
    DocumentStatus.UNDER_REVIEW: 3,
    DocumentStatus.UPLOADED: 2,
    DocumentStatus.REJECTED: 1,
    DocumentStatus.NOT_UPLOADED: 0,
}


@dataclass(frozen=True)
class DocState:
    id: str
    file_name: str
    verification_status: DocumentStatus
    extraction_status: ExtractionStatus = ExtractionStatus.NOT_STARTED


@dataclass(frozen=True)
class ManualCheck:
    status: DocumentStatus
    remarks: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None


@dataclass(frozen=True)
class ItemState:
    config: ChecklistConfig
    required: bool
    status: DocumentStatus
    source: Literal["DOCUMENT", "MANUAL", "NONE"]
    documents: Sequence[DocState] = ()
    manual: ManualCheck | None = None
    has_mismatch: bool = False


@dataclass(frozen=True)
class Summary:
    required_total: int
    verified: int
    under_review: int
    uploaded: int
    rejected: int
    missing: int
    flagged: int
    complete: bool


@dataclass(frozen=True)
class Readiness:
    ready: bool
    reasons: list[str] = field(default_factory=list)


def is_required(config: ChecklistConfig, invoice_has_payments: bool) -> bool:
    return config.requirement == "ALWAYS" or invoice_has_payments


def document_status(documents: Sequence[DocState]) -> DocumentStatus:
    """The status represented by a set of uploaded documents."""
    if not documents:
        return DocumentStatus.NOT_UPLOADED
    return max((d.verification_status for d in documents), key=lambda s: _PRECEDENCE[s])


def effective_status(
    documents: Sequence[DocState], manual: ManualCheck | None
) -> tuple[DocumentStatus, Literal["DOCUMENT", "MANUAL", "NONE"]]:
    """A verified document always counts. Otherwise the latest manual review decides. Otherwise the documents do."""
    from_docs = document_status(documents)
    if from_docs == DocumentStatus.VERIFIED:
        return from_docs, "DOCUMENT"
    if manual is not None:
        return manual.status, "MANUAL"
    return from_docs, ("DOCUMENT" if documents else "NONE")


def build_item(
    config: ChecklistConfig,
    documents: Sequence[DocState],
    manual: ManualCheck | None,
    invoice_has_payments: bool,
    has_mismatch: bool = False,
) -> ItemState:
    status, source = effective_status(documents, manual)
    return ItemState(
        config=config,
        required=is_required(config, invoice_has_payments),
        status=status,
        source=source,
        documents=tuple(documents),
        manual=manual,
        has_mismatch=has_mismatch,
    )


def summarise(items: Sequence[ItemState]) -> Summary:
    required = [i for i in items if i.required]
    count = lambda s: sum(1 for i in required if i.status == s)  # noqa: E731
    flagged = sum(1 for i in items if i.has_mismatch)
    verified = count(DocumentStatus.VERIFIED)
    return Summary(
        required_total=len(required),
        verified=verified,
        under_review=count(DocumentStatus.UNDER_REVIEW),
        uploaded=count(DocumentStatus.UPLOADED),
        rejected=count(DocumentStatus.REJECTED),
        missing=count(DocumentStatus.NOT_UPLOADED) + count(DocumentStatus.REJECTED),
        flagged=flagged,
        complete=bool(required) and verified == len(required) and flagged == 0,
    )


def assess_readiness(invoice_status: str, items: Sequence[ItemState]) -> Readiness:
    """'Ready for export filing' (simulated): paid in full, every required document verified, nothing flagged."""
    reasons: list[str] = []
    if invoice_status != "PAID":
        reasons.append("The invoice is not paid in full yet")
    summary = summarise(items)
    not_verified = [i.config.label for i in items if i.required and i.status != DocumentStatus.VERIFIED]
    if not_verified:
        reasons.append(f"Documents not verified: {', '.join(not_verified)}")
    flagged = [i.config.label for i in items if i.has_mismatch]
    if flagged:
        reasons.append(f"Differences from the invoice need review: {', '.join(flagged)}")
    return Readiness(ready=not reasons and summary.complete, reasons=reasons)
