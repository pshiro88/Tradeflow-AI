import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.money import to_money
from app.models.document import ComplianceCheck, Document
from app.models.enums import InvoiceStatus
from app.models.invoice import Invoice
from app.models.user import User
from app.repositories.invoice_repository import InvoiceRepository

ISSUED_EXCLUDED = (InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED)


class ComplianceRepository:
    def __init__(self, db: Session, today: date) -> None:
        self.db = db
        self.today = today

    def issued_invoices(self) -> list[tuple[Invoice, Decimal, str]]:
        """(invoice, amount received, derived status) for every issued invoice, soonest due first."""
        stmt = (
            select(
                Invoice,
                InvoiceRepository.received_expression().label("received"),
                InvoiceRepository.status_expression(self.today).label("status"),
            )
            .where(Invoice.status.notin_(ISSUED_EXCLUDED))
            .order_by(Invoice.due_date, Invoice.invoice_number)
        )
        return [(inv, to_money(r), s) for inv, r, s in self.db.execute(stmt).unique().all()]

    def documents_for(self, invoice_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Document]]:
        grouped: dict[uuid.UUID, list[Document]] = defaultdict(list)
        if not invoice_ids:
            return grouped
        stmt = select(Document).where(Document.invoice_id.in_(invoice_ids)).order_by(Document.created_at)
        for doc in self.db.scalars(stmt):
            grouped[doc.invoice_id].append(doc)  # type: ignore[index]
        return grouped

    def latest_checks(self, invoice_ids: list[uuid.UUID]) -> dict[tuple[uuid.UUID, str], tuple[ComplianceCheck, str | None]]:
        """The most recent manual review per (invoice, document type). Earlier ones stay as history."""
        latest: dict[tuple[uuid.UUID, str], tuple[ComplianceCheck, str | None]] = {}
        if not invoice_ids:
            return latest
        stmt = (
            select(ComplianceCheck, User.full_name)
            .outerjoin(User, User.id == ComplianceCheck.reviewed_by)
            .where(ComplianceCheck.invoice_id.in_(invoice_ids))
            .order_by(ComplianceCheck.created_at, ComplianceCheck.id)
        )
        for check, reviewer in self.db.execute(stmt).all():
            latest[(check.invoice_id, check.document_type)] = (check, reviewer)
        return latest

    def add_check(self, check: ComplianceCheck) -> ComplianceCheck:
        self.db.add(check)
        self.db.flush()
        return check
