import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, ConflictError, NotFoundError
from app.models.document import ComplianceCheck, Document
from app.models.enums import DocumentStatus, InvoiceStatus
from app.models.invoice import Invoice
from app.models.user import User
from app.repositories.compliance_repository import ComplianceRepository
from app.repositories.invoice_repository import InvoiceRepository
from app.schemas.common import Page
from app.schemas.compliance import (
    CheckRequest,
    Checklist,
    ChecklistDocument,
    ChecklistItem,
    ChecklistSummary,
    Lifecycle,
    LifecycleStep,
    OverviewFilters,
    OverviewItem,
    Readiness,
)
from app.schemas.document import FindingOut
from app.services.audit_service import record_audit
from app.services.compliance_rules import (
    CHECKLIST,
    DISCLAIMER,
    DocState,
    ItemState,
    ManualCheck,
    assess_readiness,
    build_item,
    summarise,
)
from app.services.document_consistency import InvoiceFacts, compare_with_invoice

MIN_REMARK_CHARS = 3
REQUIREMENT_NOTES = {"AFTER_PAYMENT": "Required once a payment has been received"}
ISSUED_BLOCKED = (InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED)


class ComplianceService:
    def __init__(self, db: Session, today: date | None = None) -> None:
        self.db = db
        self.today = today or date.today()
        self.repo = ComplianceRepository(db, self.today)
        self.invoices = InvoiceRepository(db)

    # ================================================================== checklist

    def checklist(self, invoice_id: uuid.UUID) -> Checklist:
        row = self.invoices.get_with_totals(invoice_id, self.today)
        if row is None:
            raise NotFoundError("Invoice not found")
        invoice, received, status = row
        docs = self.repo.documents_for([invoice.id]).get(invoice.id, [])
        checks = self.repo.latest_checks([invoice.id])
        items, findings = self._build(invoice, received, docs, checks)
        summary = summarise(items)
        readiness = assess_readiness(status, items)
        return Checklist(
            invoice_id=invoice.id,
            invoice_number=invoice.invoice_number,
            buyer_name=invoice.buyer.buyer_name,
            invoice_status=InvoiceStatus(status),
            items=[self._item_out(i, findings[i.config.document_type.value]) for i in items],
            summary=ChecklistSummary(**summary.__dict__),
            readiness=Readiness(ready=readiness.ready, reasons=readiness.reasons),
            disclaimer=DISCLAIMER,
        )

    def add_check(self, invoice_id: uuid.UUID, payload: CheckRequest, user: User) -> Checklist:
        """Record a person's review of one checklist item. Append-only: earlier reviews remain as history."""
        row = self.invoices.get_with_totals(invoice_id, self.today)
        if row is None:
            raise NotFoundError("Invoice not found")
        invoice = row[0]
        if invoice.status in ISSUED_BLOCKED:
            raise ConflictError("Documents are tracked for issued invoices only")
        config = next((c for c in CHECKLIST if c.document_type == payload.document_type), None)
        if config is None:
            raise BusinessValidationError("That document type is not part of the checklist")

        docs = self.repo.documents_for([invoice.id]).get(invoice.id, [])
        has_document = any(d.document_type == config.document_type and d.verification_status != DocumentStatus.REJECTED for d in docs)
        remarks = payload.remarks or None
        if payload.status == DocumentStatus.VERIFIED and not has_document and (remarks is None or len(remarks) < MIN_REMARK_CHARS):
            raise BusinessValidationError(
                "No document is uploaded for this item, so please say in the remarks how it was verified (for example, a paper copy seen)"
            )

        previous = self.repo.latest_checks([invoice.id]).get((invoice.id, config.document_type.value))
        check = self.repo.add_check(
            ComplianceCheck(
                invoice_id=invoice.id, document_type=config.document_type.value, status=payload.status,
                remarks=remarks, reviewed_by=user.id,
            )
        )
        record_audit(
            self.db, user_id=user.id, action="COMPLIANCE_CHECK_RECORDED", entity_type="invoice", entity_id=invoice.id,
            old_values={"document_type": config.document_type, "status": previous[0].status} if previous else None,
            new_values={"document_type": config.document_type, "status": payload.status, "remarks": remarks, "check_id": check.id},
        )
        self.db.commit()
        return self.checklist(invoice_id)

    # ================================================================== overview

    def overview(self, filters: OverviewFilters, *, page: int, page_size: int) -> Page[OverviewItem]:
        """Every issued invoice with its checklist progress, incomplete ones first."""
        issued = self.repo.issued_invoices()
        ids = [inv.id for inv, _, _ in issued]
        docs, checks = self.repo.documents_for(ids), self.repo.latest_checks(ids)
        rows: list[OverviewItem] = []
        for invoice, received, status in issued:
            items, _ = self._build(invoice, received, docs.get(invoice.id, []), checks)
            summary, readiness = summarise(items), assess_readiness(status, items)
            rows.append(
                OverviewItem(
                    invoice_id=invoice.id, invoice_number=invoice.invoice_number, buyer_name=invoice.buyer.buyer_name,
                    currency=invoice.currency, invoice_status=InvoiceStatus(status), due_date=invoice.due_date,
                    required_total=summary.required_total, verified=summary.verified, missing=summary.missing,
                    flagged=summary.flagged, complete=summary.complete, ready=readiness.ready,
                )
            )
        if filters.search:
            term = filters.search.strip().lower()
            rows = [r for r in rows if term in r.invoice_number.lower() or term in r.buyer_name.lower()]
        if filters.incomplete_only:
            rows = [r for r in rows if not r.complete]
        rows.sort(key=lambda r: (r.complete, r.due_date, r.invoice_number))
        start = (page - 1) * page_size
        return Page.build(rows[start : start + page_size], len(rows), page, page_size)

    # ================================================================== lifecycle (all roles; counts only)

    def lifecycle(self, invoice_id: uuid.UUID) -> Lifecycle:
        """Where an invoice is on its way from issue to 'ready for export filing' (a simulated checklist, not a filing)."""
        row = self.invoices.get_with_totals(invoice_id, self.today)
        if row is None:
            raise NotFoundError("Invoice not found")
        invoice, received, status = row
        cur = invoice.currency
        payments = [p for _, p in self.invoices.payments_for(invoice.id)]
        first_paid = payments[0].transaction_date if payments else None
        last_paid = payments[-1].transaction_date if payments else None
        note = "Readiness is a checklist only. TradeFlow does not file an eBRC, FIRA or anything else with an authority."

        if status == InvoiceStatus.CANCELLED.value:
            return Lifecycle(
                invoice_id=invoice.id, readiness=Readiness(ready=False, reasons=["The invoice is cancelled"]), note=note,
                steps=[LifecycleStep(key=k, label=label, state="NOT_APPLICABLE", date=None, detail="Invoice cancelled")
                       for k, label in _STEP_LABELS],
            )

        docs = self.repo.documents_for([invoice.id]).get(invoice.id, [])
        items, _ = self._build(invoice, received, docs, self.repo.latest_checks([invoice.id]))
        summary, readiness = summarise(items), assess_readiness(status, items)
        draft = status == InvoiceStatus.DRAFT.value
        paid = status == InvoiceStatus.PAID.value

        steps = [
            LifecycleStep(key="INVOICED", label=_STEP_LABELS[0][1], state="PENDING" if draft else "DONE",
                          date=None if draft else invoice.invoice_date,
                          detail="Still a draft: publish it to issue it" if draft else f"Issued to {invoice.buyer.buyer_name}"),
            LifecycleStep(key="PAYMENT_RECEIVED", label=_STEP_LABELS[1][1], state="DONE" if received > 0 else "PENDING",
                          date=first_paid,
                          detail=f"{cur} {received:,.2f} of {cur} {invoice.total_amount:,.2f} received" if received > 0 else "No payment received yet"),
            LifecycleStep(key="PAID_IN_FULL", label=_STEP_LABELS[2][1],
                          state="DONE" if paid else ("IN_PROGRESS" if received > 0 else "PENDING"),
                          date=last_paid if paid else None,
                          detail="Fully settled" if paid else f"{cur} {invoice.total_amount - received:,.2f} still outstanding"),
            LifecycleStep(key="DOCUMENTS_VERIFIED", label=_STEP_LABELS[3][1],
                          state="DONE" if summary.complete else ("IN_PROGRESS" if (summary.verified or summary.under_review or summary.uploaded) else "PENDING"),
                          date=None,
                          detail=f"{summary.verified} of {summary.required_total} required documents verified"
                                 + (f"; {summary.flagged} differ from the invoice" if summary.flagged else "")),
            LifecycleStep(key="FILING_READINESS", label=_STEP_LABELS[4][1], state="DONE" if readiness.ready else "PENDING",
                          date=None,
                          detail="Paid, documents verified and consistent" if readiness.ready else "; ".join(readiness.reasons)),
        ]
        return Lifecycle(invoice_id=invoice.id, steps=steps, readiness=Readiness(ready=readiness.ready, reasons=readiness.reasons), note=note)

    # ================================================================== helpers

    def _build(
        self, invoice: Invoice, received: Decimal, docs: list[Document], checks: dict
    ) -> tuple[list[ItemState], dict[str, tuple[str | None, list[FindingOut]]]]:
        facts = InvoiceFacts(
            invoice_number=invoice.invoice_number, exporter_name=invoice.exporter.company_name,
            buyer_name=invoice.buyer.buyer_name, currency=invoice.currency, total_amount=invoice.total_amount,
            invoice_date=invoice.invoice_date, due_date=invoice.due_date,
        )
        items: list[ItemState] = []
        findings: dict[str, tuple[str | None, list[FindingOut]]] = {}
        for config in CHECKLIST:
            of_type = [d for d in docs if d.document_type == config.document_type]
            states = [
                DocState(id=str(d.id), file_name=d.file_name, verification_status=d.verification_status, extraction_status=d.extraction_status)
                for d in of_type
            ]
            stored = checks.get((invoice.id, config.document_type.value))
            manual = (
                ManualCheck(status=stored[0].status, remarks=stored[0].remarks, reviewed_by=stored[1], reviewed_at=stored[0].created_at)
                if stored else None
            )
            compared, found = self._compare(of_type, facts)
            findings[config.document_type.value] = (compared, found)
            items.append(
                build_item(config, states, manual, received > 0, has_mismatch=any(f.status == "MISMATCH" for f in found))
            )
        return items, findings

    @staticmethod
    def _compare(docs: list[Document], facts: InvoiceFacts) -> tuple[str | None, list[FindingOut]]:
        """Compare the latest usable document of this type with the invoice (confirmed values win over AI drafts)."""
        usable = [d for d in docs if d.extracted_data and d.verification_status != DocumentStatus.REJECTED]
        if not usable:
            return None, []
        doc = max(usable, key=lambda d: d.created_at)
        confirmed = (doc.confirmed_data or {}).get("fields") if doc.verification_status == DocumentStatus.VERIFIED else None
        fields = confirmed or doc.extracted_data["fields"]
        return doc.file_name, [FindingOut(**f.__dict__) for f in compare_with_invoice(fields, facts)]

    @staticmethod
    def _item_out(item: ItemState, compared: tuple[str | None, list[FindingOut]]) -> ChecklistItem:
        manual = item.manual if item.source == "MANUAL" else None
        return ChecklistItem(
            document_type=item.config.document_type,
            label=item.config.label,
            required=item.required,
            requirement_note=REQUIREMENT_NOTES.get(item.config.requirement),
            status=item.status,
            source=item.source,
            documents=[
                ChecklistDocument(
                    id=uuid.UUID(d.id), file_name=d.file_name, verification_status=d.verification_status,
                    extraction_status=d.extraction_status,
                )
                for d in item.documents
            ],
            remarks=manual.remarks if manual else None,
            reviewed_by=manual.reviewed_by if manual else None,
            reviewed_at=manual.reviewed_at if manual else None,
            compared_document=compared[0],
            findings=compared[1],
            has_mismatch=item.has_mismatch,
        )


_STEP_LABELS = (
    ("INVOICED", "Invoiced"),
    ("PAYMENT_RECEIVED", "Payment received"),
    ("PAID_IN_FULL", "Reconciled and paid in full"),
    ("DOCUMENTS_VERIFIED", "Documents verified"),
    ("FILING_READINESS", "Ready for export filing (simulated)"),
)
