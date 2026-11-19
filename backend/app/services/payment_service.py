import csv
import io
import uuid
from datetime import date
from pathlib import PurePath

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import BusinessValidationError, NotFoundError, PayloadTooLargeError
from app.models.payment import ImportBatch
from app.models.user import User
from app.repositories.payment_repository import PaymentRepository, SortDir, SortField
from app.schemas.common import Page
from app.schemas.payment import (
    ImportBatchDetail,
    ImportBatchOut,
    ImportRowError,
    PaymentAllocationOut,
    PaymentDetail,
    PaymentFilters,
    PaymentListItem,
)
from app.services.audit_service import record_audit
from app.services.payment_import import (
    CSV_COLUMNS,
    ParsedRow,
    ValidRow,
    parse_csv,
    sanitize_csv_cell,
    validate_row,
)

MAX_STORED_VALUE_LEN = 255


class PaymentService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = PaymentRepository(db)

    # ------------------------------------------------------------------ reads

    def list_payments(
        self, filters: PaymentFilters, *, page: int, page_size: int, sort_by: SortField, sort_dir: SortDir
    ) -> Page[PaymentListItem]:
        rows, total = self.repo.list_page(filters, page=page, page_size=page_size, sort_by=sort_by, sort_dir=sort_dir)
        items = [self._list_item(p, allocated) for p, allocated in rows]
        return Page.build(items, total, page, page_size)

    def get_payment(self, payment_id: uuid.UUID) -> PaymentDetail:
        row = self.repo.get_with_allocated(payment_id)
        if row is None:
            raise NotFoundError("Payment not found")
        payment, allocated = row
        allocations = [
            PaymentAllocationOut(
                id=a.id,
                invoice_id=a.invoice_id,
                invoice_number=number,
                allocated_amount=a.allocated_amount,
                currency=a.currency,
                allocation_type=a.allocation_type,
                created_at=a.created_at,
            )
            for a, number in self.repo.allocations_for(payment.id)
        ]
        return PaymentDetail(
            **self._list_item(payment, allocated).model_dump(),
            bank_reference=payment.bank_reference,
            import_file_name=self.repo.batch_file_name(payment.import_batch_id),
            allocations=allocations,
        )

    def get_batch(self, batch_id: uuid.UUID) -> ImportBatchDetail:
        batch = self.repo.get_batch(batch_id)
        if batch is None:
            raise NotFoundError("Import batch not found")
        return self._batch_detail(batch)

    def recent_batches(self, limit: int = 10) -> list[ImportBatchOut]:
        return [ImportBatchOut.model_validate(b) for b in self.repo.recent_batches(limit)]

    def build_error_report(self, batch_id: uuid.UUID) -> str:
        """CSV of rejected/duplicate rows with the reasons, so the user can fix and re-upload."""
        batch = self.get_batch(batch_id)
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\r\n")
        writer.writerow(["row_number", "category", "issues", *CSV_COLUMNS])
        for err in batch.errors:
            issues = "; ".join(f"{i.field}: {i.message}" for i in err.issues)
            cells = [err.row, err.category, issues, *(err.values.get(c, "") for c in CSV_COLUMNS)]
            writer.writerow([sanitize_csv_cell(c) for c in cells])
        return out.getvalue()

    # ------------------------------------------------------------------ import

    def import_csv(self, content: bytes, file_name: str, user: User, *, today: date | None = None) -> ImportBatchDetail:
        """Validate and import a bank CSV.

        Valid new rows are imported. Invalid rows and duplicates are skipped and reported with a reason.
        Importing the same file again imports nothing (the transaction_reference unique constraint is
        the final guard). The batch record, payments and audit entry commit together or not at all.
        """
        settings = get_settings()
        if len(content) > settings.max_upload_mb * 1024 * 1024:
            raise PayloadTooLargeError(f"The file is larger than the {settings.max_upload_mb} MB limit")
        safe_name = self._safe_file_name(file_name)

        parsed_rows = parse_csv(content, max_rows=settings.max_import_rows)
        if not parsed_rows:
            raise BusinessValidationError("The file has a header but no transactions")

        today = today or date.today()
        errors: list[ImportRowError] = []
        candidates: list[ValidRow] = []
        first_line_of: dict[str, int] = {}

        for parsed in parsed_rows:
            valid, issues = validate_row(parsed, today)
            if valid is None:
                errors.append(self._error(parsed, "VALIDATION", [(i.field, i.message) for i in issues]))
                continue
            first = first_line_of.get(valid.transaction_reference)
            if first is not None:
                msg = f"Transaction reference repeated in this file (first seen on line {first})"
                errors.append(self._error(parsed, "DUPLICATE_IN_FILE", [("transaction_reference", msg)]))
                continue
            first_line_of[valid.transaction_reference] = valid.line
            candidates.append(valid)

        existing = self.repo.existing_references([c.transaction_reference for c in candidates])
        to_insert: list[ValidRow] = []
        by_line = {p.line: p for p in parsed_rows}
        for cand in candidates:
            if cand.transaction_reference in existing:
                errors.append(self._duplicate_existing(by_line[cand.line]))
            else:
                to_insert.append(cand)

        batch = self.repo.add_batch(ImportBatch(file_name=safe_name, imported_by=user.id))
        inserted = self.repo.bulk_insert(to_insert, batch.id)
        for row in to_insert:  # lost a race with a concurrent import of the same reference
            if row.transaction_reference not in inserted:
                errors.append(self._duplicate_existing(by_line[row.line]))

        errors.sort(key=lambda e: e.row)
        duplicates = sum(1 for e in errors if e.category != "VALIDATION")
        batch.total_rows = len(parsed_rows)
        batch.accepted_rows = len(inserted)
        batch.duplicate_rows = duplicates
        batch.rejected_rows = len(errors) - duplicates
        batch.errors = [e.model_dump(mode="json") for e in errors]

        record_audit(
            self.db,
            user_id=user.id,
            action="PAYMENTS_IMPORTED",
            entity_type="import_batch",
            entity_id=batch.id,
            new_values={
                "file_name": safe_name,
                "total_rows": batch.total_rows,
                "accepted_rows": batch.accepted_rows,
                "duplicate_rows": batch.duplicate_rows,
                "rejected_rows": batch.rejected_rows,
            },
        )
        self.db.commit()
        return self._batch_detail(batch)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _safe_file_name(file_name: str) -> str:
        """Keep only the base name (defends against path tricks) and require a .csv extension."""
        base = PurePath(file_name.replace("\\", "/")).name.strip()
        if not base.lower().endswith(".csv"):
            raise BusinessValidationError("Only .csv files are supported")
        return base[:255]

    @staticmethod
    def _error(parsed: ParsedRow, category: str, issues: list[tuple[str, str]]) -> ImportRowError:
        values = {k: v[:MAX_STORED_VALUE_LEN] for k, v in parsed.raw.items() if k in CSV_COLUMNS}
        return ImportRowError(
            row=parsed.line,
            transaction_reference=(values.get("transaction_reference", "").strip() or None),
            category=category,  # type: ignore[arg-type]
            issues=[{"field": f, "message": m} for f, m in issues],
            values=values,
        )

    def _duplicate_existing(self, parsed: ParsedRow) -> ImportRowError:
        msg = "A payment with this transaction reference has already been imported"
        return self._error(parsed, "DUPLICATE_EXISTING", [("transaction_reference", msg)])

    @staticmethod
    def _list_item(payment, allocated) -> PaymentListItem:  # noqa: ANN001
        return PaymentListItem(
            id=payment.id,
            transaction_reference=payment.transaction_reference,
            payment_reference=payment.payment_reference,
            sender_name=payment.sender_name,
            currency=payment.currency,
            amount=payment.amount,
            allocated_amount=allocated,
            transaction_date=payment.transaction_date,
            created_at=payment.created_at,
            status=payment.status,
            import_batch_id=payment.import_batch_id,
        )

    @staticmethod
    def _batch_detail(batch: ImportBatch) -> ImportBatchDetail:
        return ImportBatchDetail(
            id=batch.id,
            file_name=batch.file_name,
            total_rows=batch.total_rows,
            accepted_rows=batch.accepted_rows,
            rejected_rows=batch.rejected_rows,
            duplicate_rows=batch.duplicate_rows,
            created_at=batch.created_at,
            errors=[ImportRowError.model_validate(e) for e in (batch.errors or [])],
        )
