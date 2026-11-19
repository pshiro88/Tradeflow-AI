import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePath

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import (
    AIResponseError,
    AIUnavailableError,
    BusinessValidationError,
    ConflictError,
    NotFoundError,
)
from app.models.document import Document
from app.models.enums import DocumentStatus, DocumentType, ExtractionStatus
from app.models.user import User
from app.repositories.document_repository import DocumentRepository
from app.schemas.common import Page
from app.schemas.document import (
    ConfirmationInfo,
    DocumentDetail,
    DocumentExplanation,
    DocumentFilters,
    DocumentListItem,
    ExtractionInfo,
    FieldIssueOut,
    FindingOut,
    VerifyRequest,
)
from app.services import ai_audit
from app.services.ai_guardrails import check_rewrite
from app.services.audit_service import record_audit
from app.services.document_consistency import InvoiceFacts, compare_with_invoice
from app.services.document_extraction import FIELD_NAMES, ExtractedFields, extract_fields
from app.services.ollama_service import LLMClient
from app.services.pdf_service import validate_and_extract

FIELD_LABELS = {
    "document_type": "Document type",
    "invoice_number": "Invoice number",
    "exporter_name": "Exporter",
    "buyer_name": "Buyer",
    "buyer_country": "Buyer country",
    "currency": "Currency",
    "invoice_amount": "Amount",
    "invoice_date": "Invoice date",
    "due_date": "Due date",
}

EXPLAIN_SYSTEM = (
    "You rewrite a trade-document check summary so an operations colleague can read it easily. "
    "Keep EVERY name, reference, date, amount and field name exactly as in the DRAFT, and keep everything that is "
    "missing, unverified or different. Do not add, remove or reinterpret anything, and never claim legal or "
    "regulatory approval. Do not mention these instructions."
)


class DocumentService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = DocumentRepository(db)
        self.settings = get_settings()

    # ================================================================== upload

    def upload(
        self, content: bytes, file_name: str, document_type: DocumentType, invoice_id: uuid.UUID | None, user: User
    ) -> DocumentDetail:
        """Validate a PDF, store it under a generated name, and register it. No AI is involved yet."""
        safe_name = self._safe_file_name(file_name)
        validate_and_extract(
            content, max_bytes=self.settings.max_upload_mb * 1024 * 1024, max_pages=self.settings.max_pdf_pages
        )
        if invoice_id is not None and not self.repo.invoice_exists(invoice_id):
            raise BusinessValidationError("Invoice not found")

        stored_name = f"{uuid.uuid4()}.pdf"  # never derived from user input: no path traversal possible
        path = self._upload_dir() / stored_name
        path.write_bytes(content)
        try:
            document = self.repo.add(
                Document(
                    invoice_id=invoice_id,
                    file_name=safe_name,
                    file_path=stored_name,
                    document_type=document_type,
                    extraction_status=ExtractionStatus.NOT_STARTED,
                    verification_status=DocumentStatus.UPLOADED,
                    uploaded_by=user.id,
                )
            )
            record_audit(
                self.db,
                user_id=user.id,
                action="DOCUMENT_UPLOADED",
                entity_type="document",
                entity_id=document.id,
                new_values={"file_name": safe_name, "document_type": document_type, "invoice_id": invoice_id},
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            path.unlink(missing_ok=True)  # do not leave orphan files behind
            raise
        return self.get(document.id)

    # ================================================================== reads

    def list_documents(self, filters: DocumentFilters, *, page: int, page_size: int) -> Page[DocumentListItem]:
        rows, total = self.repo.list_page(filters, page=page, page_size=page_size)
        return Page.build([self._item(d, n, u) for d, n, u in rows], total, page, page_size)

    def get(self, document_id: uuid.UUID) -> DocumentDetail:
        row = self.repo.get_row(document_id)
        if row is None:
            raise NotFoundError("Document not found")
        document, number, uploader = row
        return DocumentDetail(
            **self._item(document, number, uploader).model_dump(),
            extraction=self._extraction_info(document),
            confirmation=self._confirmation_info(document),
        )

    # ================================================================== AI extraction

    def extract(self, document_id: uuid.UUID, user: User, llm: LLMClient) -> DocumentDetail:
        """Run the AI extraction. The result is a DRAFT for a person to review: no financial record is created."""
        try:
            document = self.repo.lock(document_id, nowait=True)  # one extraction per document at a time
        except OperationalError as exc:
            self.db.rollback()
            raise ConflictError("This document is already being processed. Please wait a moment.") from exc
        if document is None:
            raise NotFoundError("Document not found")
        if document.verification_status == DocumentStatus.VERIFIED:
            raise ConflictError("This document has already been verified and cannot be re-extracted")

        pdf = validate_and_extract(
            self._read(document), max_bytes=self.settings.max_upload_mb * 1024 * 1024, max_pages=self.settings.max_pdf_pages
        )
        started = ai_audit.start_timer()
        summary = f"Extract invoice fields from '{document.file_name}' ({pdf.page_count} page(s), {len(pdf.text)} characters)"
        try:
            outcome = extract_fields(llm, pdf.text, max_chars=self.settings.max_llm_chars)
        except (AIUnavailableError, AIResponseError) as exc:
            document.extraction_status = ExtractionStatus.FAILED
            self.db.commit()
            ai_audit.record_ai_call(
                self.db, user_id=user.id, operation="EXTRACT", model=llm.model, request_summary=summary,
                response_summary=exc.message, status="FAILED", started=started, details={"document_id": str(document.id)},
            )
            raise

        extracted = outcome.fields.model_dump(mode="json")
        document.extracted_data = {
            "fields": extracted,
            "quality": outcome.quality,
            "llm_confidence": outcome.llm_confidence,
            "issues": [i.model_dump() for i in outcome.issues],
            "model": outcome.model,
            "truncated": outcome.truncated,
            "page_count": pdf.page_count,
        }
        document.extraction_status = ExtractionStatus.COMPLETED
        document.verification_status = DocumentStatus.UNDER_REVIEW
        found = sum(1 for v in extracted.values() if v is not None)
        flagged = sorted(k for k, q in outcome.quality.items() if q == "NOT_FOUND_IN_TEXT")
        record_audit(
            self.db, user_id=user.id, action="DOCUMENT_EXTRACTED", entity_type="document", entity_id=document.id,
            new_values={"fields_found": found, "flagged_not_in_text": flagged, "issues": len(outcome.issues)},
        )
        self.db.commit()
        ai_audit.record_ai_call(
            self.db, user_id=user.id, operation="EXTRACT", model=llm.model, request_summary=summary,
            response_summary=f"Extracted {found} of {len(FIELD_NAMES)} fields; {len(flagged)} not found in the text; {len(outcome.issues)} invalid",
            status="SUCCESS", started=started,
            details={"document_id": str(document.id), "fields_found": found, "flagged": flagged, "truncated": outcome.truncated},
        )
        return self.get(document.id)

    # ================================================================== human verification

    def verify(self, document_id: uuid.UUID, payload: VerifyRequest, user: User) -> DocumentDetail:
        """A person confirms (optionally correcting) or rejects. The AI never does this, and nothing financial is created."""
        document = self.repo.lock(document_id)
        if document is None:
            raise NotFoundError("Document not found")
        if document.verification_status == DocumentStatus.VERIFIED:
            raise ConflictError("This document has already been verified")

        before = document.verification_status
        if payload.decision == "VERIFIED":
            if document.extraction_status != ExtractionStatus.COMPLETED or not document.extracted_data:
                raise BusinessValidationError("Extract the document first, then review and confirm the values")
            fields = (payload.fields or self._extracted_fields(document)).model_dump(mode="json")
            document.confirmed_data = {
                "fields": fields,
                "decision": "VERIFIED",
                "note": payload.note,
                "by": user.full_name,
                "at": datetime.now(UTC).isoformat(),
            }
            document.verification_status = DocumentStatus.VERIFIED
            changed = {k: {"ai": document.extracted_data["fields"].get(k), "confirmed": v} for k, v in fields.items() if document.extracted_data["fields"].get(k) != v}
            action, new_values = "DOCUMENT_VERIFIED", {"corrected_fields": changed, "note": payload.note}
        else:
            document.confirmed_data = {
                "fields": {},
                "decision": "REJECTED",
                "note": payload.note,
                "by": user.full_name,
                "at": datetime.now(UTC).isoformat(),
            }
            document.verification_status = DocumentStatus.REJECTED
            action, new_values = "DOCUMENT_REJECTED", {"note": payload.note}

        record_audit(
            self.db, user_id=user.id, action=action, entity_type="document", entity_id=document.id,
            old_values={"verification_status": before}, new_values=new_values,
        )
        self.db.commit()
        return self.get(document.id)

    # ================================================================== explanation (FR-025)

    def explain(self, document_id: uuid.UUID, user: User, llm: LLMClient) -> DocumentExplanation:
        """Plain-language summary of what was extracted, what is missing, and what disagrees with the invoice."""
        row = self.repo.get_row(document_id)
        if row is None:
            raise NotFoundError("Document not found")
        document = row[0]
        if not document.extracted_data:
            raise BusinessValidationError("Extract the document first")

        data = document.extracted_data
        confirmed = (document.confirmed_data or {}).get("fields") if document.confirmed_data else None
        fields: dict = confirmed or data["fields"]
        quality: dict = data["quality"]

        missing = [FIELD_LABELS[k] for k in FIELD_NAMES if fields.get(k) is None]
        needs_check = [FIELD_LABELS[k] for k in FIELD_NAMES if fields.get(k) is not None and quality.get(k) == "NOT_FOUND_IN_TEXT"]

        findings: list[FindingOut] = []
        invoice_note = "This document is not linked to an invoice, so it was not compared with one."
        if document.invoice_id:
            invoice = self.repo.get_invoice(document.invoice_id)
            if invoice is not None:
                facts = InvoiceFacts(
                    invoice_number=invoice.invoice_number, exporter_name=invoice.exporter.company_name,
                    buyer_name=invoice.buyer.buyer_name, currency=invoice.currency, total_amount=invoice.total_amount,
                    invoice_date=invoice.invoice_date, due_date=invoice.due_date,
                )
                findings = [FindingOut(**f.__dict__) for f in compare_with_invoice(fields, facts)]
                mismatches = [f for f in findings if f.status == "MISMATCH"]
                invoice_note = (
                    f"Compared with invoice {invoice.invoice_number}: {len(mismatches)} difference(s) found."
                    if mismatches
                    else f"Compared with invoice {invoice.invoice_number}: no differences found."
                )

        deterministic = self._deterministic_summary(fields, missing, needs_check, findings, invoice_note, bool(confirmed))
        summary, generated_by, ai_note = deterministic, "RULES", None
        started = ai_audit.start_timer()
        request = f"Explain document '{document.file_name}'"
        try:
            # The model only rewords the finished summary; a rewrite that adds or drops a figure is rejected.
            answer = llm.chat_text(EXPLAIN_SYSTEM, f"DRAFT:\n{deterministic}\n\nRewrite the draft.")
            problems = check_rewrite(answer, deterministic)
            if not problems:
                summary, generated_by = answer, "AI"
                status = "SUCCESS"
            else:
                ai_note, status = "The AI wording changed the document details, so the standard summary is shown.", "REJECTED_UNGROUNDED"
            ai_audit.record_ai_call(
                self.db, user_id=user.id, operation="EXPLAIN_DOCUMENT", model=llm.model, request_summary=request,
                response_summary=answer, status=status, started=started, details={"document_id": str(document.id)},
            )
        except (AIUnavailableError, AIResponseError) as exc:
            ai_note = f"AI summary unavailable ({exc.message}). Showing the standard summary."
            ai_audit.record_ai_call(
                self.db, user_id=user.id, operation="EXPLAIN_DOCUMENT", model=llm.model, request_summary=request,
                response_summary=exc.message, status="UNAVAILABLE", started=started, details={"document_id": str(document.id)},
            )

        return DocumentExplanation(
            summary=summary, generated_by=generated_by, ai_note=ai_note,  # type: ignore[arg-type]
            missing_fields=missing, needs_verification=needs_check, findings=findings,
        )

    # ================================================================== helpers

    @staticmethod
    def _deterministic_summary(
        fields: dict, missing: list[str], needs_check: list[str], findings: list[FindingOut], invoice_note: str, confirmed: bool
    ) -> str:
        found = sum(1 for k in FIELD_NAMES if fields.get(k) is not None)
        parts = [f"{found} of {len(FIELD_NAMES)} fields were {'confirmed' if confirmed else 'extracted'}."]
        if missing:
            parts.append(f"Missing: {', '.join(missing)}.")
        if needs_check:
            parts.append(f"Not found in the document text, so please verify: {', '.join(needs_check)}.")
        parts.append(invoice_note)
        for finding in (f for f in findings if f.status == "MISMATCH"):
            parts.append(finding.message + ".")
        return " ".join(parts)

    def _upload_dir(self) -> Path:
        directory = Path(self.settings.upload_dir).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _read(self, document: Document) -> bytes:
        directory = self._upload_dir()
        path = (directory / document.file_path).resolve()
        if path.parent != directory:  # defence in depth against a tampered file_path
            raise BusinessValidationError("Invalid document path")
        if not path.exists():
            raise NotFoundError("The stored file for this document is missing")
        return path.read_bytes()

    @staticmethod
    def _safe_file_name(file_name: str) -> str:
        base = PurePath(file_name.replace("\\", "/")).name.strip()
        if not base.lower().endswith(".pdf"):
            raise BusinessValidationError("Only .pdf files are supported")
        return base[:255]

    @staticmethod
    def _extracted_fields(document: Document) -> ExtractedFields:
        return ExtractedFields.model_validate(document.extracted_data["fields"])

    @staticmethod
    def _item(document: Document, invoice_number: str | None, uploader: str | None) -> DocumentListItem:
        return DocumentListItem(
            id=document.id,
            invoice_id=document.invoice_id,
            invoice_number=invoice_number,
            file_name=document.file_name,
            document_type=document.document_type,
            extraction_status=document.extraction_status,
            verification_status=document.verification_status,
            uploaded_by_name=uploader,
            created_at=document.created_at,
        )

    @staticmethod
    def _extraction_info(document: Document) -> ExtractionInfo | None:
        data = document.extracted_data
        if not data:
            return None
        return ExtractionInfo(
            fields=data["fields"],
            quality=data["quality"],
            llm_confidence=data.get("llm_confidence", {}),
            issues=[FieldIssueOut(**i) for i in data.get("issues", [])],
            model=data.get("model", ""),
            truncated=data.get("truncated", False),
            page_count=data.get("page_count", 0),
        )

    @staticmethod
    def _confirmation_info(document: Document) -> ConfirmationInfo | None:
        data = document.confirmed_data
        if not data:
            return None
        at = data.get("at")
        return ConfirmationInfo(
            fields=data.get("fields", {}),
            decision=data["decision"],
            note=data.get("note"),
            by=data.get("by"),
            at=datetime.fromisoformat(at) if at else None,
        )

