"""Fixed, parameterised queries used by the Copilot's handlers.

The LLM never writes or runs SQL (BRD FR-031). Every question maps to one of these predefined queries.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.money import to_money
from app.models.audit import AIAuditLog
from app.models.enums import InvoiceStatus, ReconciliationStatus
from app.models.invoice import Invoice
from app.models.party import Buyer
from app.models.payment import Payment, ReconciliationResult
from app.repositories.invoice_repository import InvoiceRepository

ISSUED_EXCLUDED = (InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED)
DISCREPANCY_STATUSES = (
    ReconciliationStatus.MISMATCH,
    ReconciliationStatus.MANUAL_REVIEW,
    ReconciliationStatus.UNMATCHED,
    ReconciliationStatus.DUPLICATE,
)

class CopilotRepository:
    def __init__(self, db: Session, today: date) -> None:
        self.db = db
        self.today = today

    def result_for_transaction(self, transaction_reference: str) -> tuple[uuid.UUID | None, Payment] | None:
        """(reconciliation result id or None if still pending, payment) for a transaction reference."""
        payment = self.db.scalar(
            select(Payment).where(func.lower(Payment.transaction_reference) == transaction_reference.strip().lower())
        )
        if payment is None:
            return None
        result_id = self.db.scalar(select(ReconciliationResult.id).where(ReconciliationResult.payment_id == payment.id))
        return result_id, payment

    def discrepancies(
        self, start: date | None, end: date | None, limit: int
    ) -> tuple[dict[ReconciliationStatus, int], list[tuple[Payment, ReconciliationResult, str | None]]]:
        conds = [ReconciliationResult.status.in_(DISCREPANCY_STATUSES)]
        if start:
            conds.append(Payment.transaction_date >= start)
        if end:
            conds.append(Payment.transaction_date <= end)
        counts = {
            status: count
            for status, count in self.db.execute(
                select(ReconciliationResult.status, func.count())
                .join(Payment, Payment.id == ReconciliationResult.payment_id)
                .where(*conds)
                .group_by(ReconciliationResult.status)
            ).all()
        }
        rows = self.db.execute(
            select(Payment, ReconciliationResult, Invoice.invoice_number)
            .join(ReconciliationResult, ReconciliationResult.payment_id == Payment.id)
            .outerjoin(Invoice, Invoice.id == ReconciliationResult.invoice_id)
            .where(*conds)
            .order_by(Payment.transaction_date.desc(), Payment.transaction_reference)
            .limit(limit)
        ).all()
        return counts, [(p, r, n) for p, r, n in rows]

    def outstanding_by_buyer(self) -> list[tuple[str, str, Decimal, int]]:
        """(buyer, currency, outstanding, open invoice count). Never summed across currencies."""
        received = InvoiceRepository.received_expression()
        rows = (
            select(
                Buyer.buyer_name.label("buyer"),
                Invoice.currency.label("currency"),
                (Invoice.total_amount - received).label("outstanding"),
            )
            .join(Buyer, Buyer.id == Invoice.buyer_id)
            .where(Invoice.status.notin_(ISSUED_EXCLUDED), Invoice.total_amount > received)
            .subquery()
        )
        stmt = (
            select(rows.c.buyer, rows.c.currency, func.sum(rows.c.outstanding), func.count())
            .group_by(rows.c.buyer, rows.c.currency)
            .order_by(rows.c.currency, func.sum(rows.c.outstanding).desc())
        )
        return [(b, c, to_money(o), n) for b, c, o, n in self.db.execute(stmt).all()]

    def chat_history(self, user_id: uuid.UUID, limit: int) -> list[AIAuditLog]:
        stmt = (
            select(AIAuditLog)
            .where(AIAuditLog.user_id == user_id, AIAuditLog.operation_type == "CHAT")
            .order_by(AIAuditLog.created_at.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt))
