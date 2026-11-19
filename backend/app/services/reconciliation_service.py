"""Reconciliation orchestration: transactions, locking, persistence and manual review.

The matching *decisions* come from the pure engine (`reconciliation_engine`). This layer only:
  - loads current state under row locks,
  - feeds payments to the engine in a fixed order (so earlier allocations affect later payments),
  - persists the outcomes, append-only allocations and audit records in ONE transaction,
  - lets a person approve or reject uncertain outcomes (never the AI, never silently).

The database triggers (app/db/triggers.py) are the last line of defence for the money invariants.
"""

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, ConflictError, NotFoundError
from app.core.money import to_money
from app.models.enums import AllocationType, ReconciliationStatus, ReviewDecision
from app.models.invoice import Invoice
from app.models.payment import Payment, PaymentAllocation, ReconciliationResult
from app.models.user import User
from app.repositories.reconciliation_repository import (
    NEEDS_ATTENTION,
    PAYABLE_EXCLUDED,
    ReconciliationRepository,
)
from app.schemas.common import Page
from app.schemas.reconciliation import (
    ApproveRequest,
    CandidateOut,
    EligibleInvoice,
    ReconciliationDetail,
    ReconciliationFilters,
    ReconciliationItem,
    RejectRequest,
    RunSummary,
    StatusSummary,
)
from app.services.audit_service import record_audit
from app.services.invoice_status import derive_status
from app.services.reconciliation_engine import (
    METHOD_NONE,
    Decision,
    InvoiceState,
    PaymentView,
    name_similarity,
    reconcile_payment,
)

ZERO = Decimal("0.00")
REVIEWABLE = (ReconciliationStatus.MANUAL_REVIEW, ReconciliationStatus.MISMATCH)  # can be rejected
APPROVABLE = NEEDS_ATTENTION  # a person may allocate these manually


class ReconciliationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = ReconciliationRepository(db)

    # ================================================================== run

    def run(self, user: User, today: date | None = None) -> RunSummary:
        """Reconcile every PENDING payment. Idempotent: payments already processed are never revisited."""
        today = today or date.today()
        try:
            summary = self._run(user, today)
            self.db.commit()
            return summary
        except IntegrityError as exc:  # a database guard rejected an allocation
            self.db.rollback()
            raise ConflictError("Reconciliation was stopped by a database integrity check; nothing was changed") from exc
        except Exception:
            self.db.rollback()
            raise

    def _run(self, user: User, today: date) -> RunSummary:
        payments = self.repo.lock_pending_payments()
        counts: dict[str, int] = {}
        if not payments:
            return RunSummary(processed=0, counts=counts, allocations_created=0)

        # Lock every invoice (payment rows first, then invoices: the same order the DB trigger uses).
        invoices = {inv.id: inv for inv in self.repo.lock_all_invoices()}
        allocated = self.repo.allocated_by_invoice()
        states: dict[str, InvoiceState] = {
            str(inv.id): InvoiceState(
                id=str(inv.id),
                invoice_number=inv.invoice_number,
                buyer_name=inv.buyer.buyer_name,
                currency=inv.currency,
                total_amount=inv.total_amount,
                allocated=allocated.get(inv.id, ZERO),
                payable=inv.status not in PAYABLE_EXCLUDED,
                status_label=inv.status.value,
            )
            for inv in invoices.values()
        }
        processed = [self._view(p) for p in self.repo.processed_payments()]

        touched: set[uuid.UUID] = set()
        allocations = 0
        for payment in payments:
            view = self._view(payment)
            decision = reconcile_payment(view, states, processed)

            self.repo.add_result(self._to_result(payment, decision))
            if decision.allocate > 0:
                invoice_id = uuid.UUID(decision.invoice_id)  # type: ignore[arg-type]
                self.repo.add_allocation(
                    PaymentAllocation(
                        payment_id=payment.id,
                        invoice_id=invoice_id,
                        allocated_amount=decision.allocate,
                        currency=payment.currency,
                        allocation_type=AllocationType.AUTO,
                        allocated_by=user.id,
                    )
                )
                state = states[decision.invoice_id]  # type: ignore[index]
                states[state.id] = replace(state, allocated=state.allocated + decision.allocate)
                touched.add(invoice_id)
                allocations += 1

            payment.status = decision.status
            if decision.status != ReconciliationStatus.DUPLICATE:
                processed.append(view)  # later payments can be recognised as duplicates of this one
            counts[decision.status.value] = counts.get(decision.status.value, 0) + 1

            record_audit(
                self.db,
                user_id=user.id,
                action="PAYMENT_RECONCILED",
                entity_type="payment",
                entity_id=payment.id,
                old_values={"status": ReconciliationStatus.PENDING},
                new_values={
                    "status": decision.status,
                    "method": decision.method,
                    "invoice_id": decision.invoice_id,
                    "allocated_amount": decision.allocate,
                },
            )

        # Keep each touched invoice's stored status aligned with its new balance.
        for invoice_id in touched:
            invoice = invoices[invoice_id]
            invoice.status = derive_status(
                invoice.status, invoice.total_amount, states[str(invoice_id)].allocated, invoice.due_date, today
            )

        record_audit(
            self.db,
            user_id=user.id,
            action="RECONCILIATION_RUN",
            entity_type="reconciliation",
            entity_id=None,
            new_values={"processed": len(payments), "counts": counts, "allocations_created": allocations},
        )
        return RunSummary(processed=len(payments), counts=counts, allocations_created=allocations)

    # ================================================================== reads

    def summary(self) -> StatusSummary:
        counts = self.repo.status_counts()
        needs = sum(counts.get(s.value, 0) for s in NEEDS_ATTENTION)
        return StatusSummary(counts=counts, total=sum(counts.values()), needs_review=needs)

    def list_results(self, filters: ReconciliationFilters, *, page: int, page_size: int) -> Page[ReconciliationItem]:
        rows, total = self.repo.list_page(filters, page=page, page_size=page_size)
        items = [self._item(result, payment, number, currency) for result, payment, number, currency in rows]
        return Page.build(items, total, page, page_size)

    def get_result(self, result_id: uuid.UUID) -> ReconciliationDetail:
        row = self.repo.get_row(result_id)
        if row is None:
            raise NotFoundError("Reconciliation result not found")
        result, payment, number, invoice_currency = row
        item = self._item(result, payment, number, invoice_currency)
        return ReconciliationDetail(
            **item.model_dump(),
            candidates=[CandidateOut.model_validate(c) for c in (result.candidates or [])],
            review_note=result.review_note,
            reviewed_by_name=self.repo.reviewer_name(result.reviewed_by),
            reviewed_at=result.reviewed_at,
            payment_unallocated=to_money(payment.amount - self.repo.allocated_for_payment(payment.id)),
        )

    def eligible_invoices(self, result_id: uuid.UUID) -> list[EligibleInvoice]:
        """Invoices a person may allocate this payment to: same currency, payable, with a balance."""
        row = self.repo.get_row(result_id)
        if row is None:
            raise NotFoundError("Reconciliation result not found")
        result, payment, _, _ = row
        candidate_ids = {c["invoice_id"] for c in (result.candidates or [])}
        eligible = [
            EligibleInvoice(
                invoice_id=inv.id,
                invoice_number=inv.invoice_number,
                buyer_name=inv.buyer.buyer_name,
                currency=inv.currency,
                outstanding=to_money(inv.total_amount - allocated),
                due_date=inv.due_date,
                name_score=name_similarity(payment.sender_name, inv.buyer.buyer_name),
                is_candidate=str(inv.id) in candidate_ids,
            )
            for inv, allocated in self.repo.payable_invoices(payment.currency)
        ]
        eligible.sort(key=lambda e: (not e.is_candidate, -e.name_score, e.due_date, e.invoice_number))
        return eligible

    # ================================================================== manual review

    def approve(self, result_id: uuid.UUID, payload: ApproveRequest, user: User) -> ReconciliationDetail:
        """A person allocates (part of) a payment to an invoice. Never crosses currencies, never over-allocates."""
        result = self._lock_result(result_id)
        if result.review_decision == ReviewDecision.APPROVED or result.status not in APPROVABLE:
            raise ConflictError("This payment has already been resolved and cannot be approved again")

        # Lock order: payment, then invoice (matches the database trigger).
        payment = self.repo.lock_payment(result.payment_id)
        invoice = self.repo.lock_invoice(payload.invoice_id)
        if invoice is None:
            raise BusinessValidationError("Invoice not found")
        if invoice.status in PAYABLE_EXCLUDED:
            raise BusinessValidationError(f"Invoice {invoice.invoice_number} is {invoice.status.value.lower()} and cannot receive payments")
        if invoice.currency != payment.currency:
            raise BusinessValidationError(
                f"Currency mismatch: the payment is in {payment.currency} and the invoice is in {invoice.currency}. "
                "Allocations across currencies are not allowed."
            )

        invoice_allocated = self.repo.allocated_for_invoice(invoice.id)
        outstanding = to_money(invoice.total_amount - invoice_allocated)
        payment_unallocated = to_money(payment.amount - self.repo.allocated_for_payment(payment.id))
        if outstanding <= 0:
            raise BusinessValidationError(f"Invoice {invoice.invoice_number} is already fully settled")
        if payment_unallocated <= 0:
            raise BusinessValidationError("This payment has no unallocated amount left")

        max_amount = min(outstanding, payment_unallocated)
        amount = to_money(payload.amount) if payload.amount is not None else max_amount
        if amount > max_amount:
            raise BusinessValidationError(
                f"Amount {amount} is too high: at most {max_amount} can be allocated "
                f"(invoice outstanding {outstanding}, payment unallocated {payment_unallocated})"
            )

        before = {
            "status": result.status,
            "invoice_id": result.invoice_id,
            "allocated_amount": result.allocated_amount,
            "review_decision": result.review_decision,
        }
        try:
            self.repo.add_allocation(
                PaymentAllocation(
                    payment_id=payment.id,
                    invoice_id=invoice.id,
                    allocated_amount=amount,
                    currency=payment.currency,
                    allocation_type=AllocationType.MANUAL,
                    allocated_by=user.id,
                )
            )
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError("The allocation was rejected by a database integrity check") from exc

        after_outstanding = to_money(outstanding - amount)
        remainder = to_money(payment_unallocated - amount)
        result.invoice_id = invoice.id
        result.invoice_amount = to_money(invoice.total_amount)
        result.previously_received = invoice_allocated
        result.allocated_amount = to_money(result.allocated_amount + amount)
        result.outstanding_after = after_outstanding
        result.match_method = "MANUAL_APPROVAL"
        result.status = ReconciliationStatus.MATCHED if after_outstanding == 0 else ReconciliationStatus.PARTIAL
        result.review_decision = ReviewDecision.APPROVED
        result.reviewed_by = user.id
        result.reviewed_at = datetime.now(UTC)
        result.review_note = payload.note
        result.explanation = self._append(
            result.explanation,
            f"Manually approved by {user.full_name}: {payment.currency} {amount:,.2f} allocated to "
            f"{invoice.invoice_number}, leaving {invoice.currency} {after_outstanding:,.2f} outstanding."
            + (f" {payment.currency} {remainder:,.2f} of the payment remains unallocated." if remainder > 0 else ""),
        )
        payment.status = result.status
        invoice.status = derive_status(
            invoice.status, invoice.total_amount, invoice_allocated + amount, invoice.due_date, date.today()
        )

        record_audit(
            self.db,
            user_id=user.id,
            action="RECONCILIATION_APPROVED",
            entity_type="reconciliation_result",
            entity_id=result.id,
            old_values=before,
            new_values={
                "status": result.status,
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "allocated_amount": amount,
                "note": payload.note,
            },
        )
        self.db.commit()
        return self.get_result(result.id)

    def reject(self, result_id: uuid.UUID, payload: RejectRequest, user: User) -> ReconciliationDetail:
        """A person rejects the engine's suggested candidate. The payment returns to UNMATCHED."""
        result = self._lock_result(result_id)
        if result.review_decision != ReviewDecision.NONE or result.status not in REVIEWABLE:
            raise ConflictError("Only an unresolved manual-review or mismatch result can be rejected")

        payment = self.repo.lock_payment(result.payment_id)
        before = {
            "status": result.status,
            "invoice_id": result.invoice_id,
            "review_decision": result.review_decision,
        }
        previous_invoice = self.repo.get_invoice_number(result.invoice_id)
        result.status = ReconciliationStatus.UNMATCHED
        result.review_decision = ReviewDecision.REJECTED
        result.invoice_id = None
        result.reviewed_by = user.id
        result.reviewed_at = datetime.now(UTC)
        result.review_note = payload.note
        result.explanation = self._append(
            result.explanation,
            f"Candidate{f' {previous_invoice}' if previous_invoice else ''} rejected by {user.full_name}. "
            "The payment is unmatched and can still be allocated manually.",
        )
        payment.status = ReconciliationStatus.UNMATCHED

        record_audit(
            self.db,
            user_id=user.id,
            action="RECONCILIATION_REJECTED",
            entity_type="reconciliation_result",
            entity_id=result.id,
            old_values=before,
            new_values={"status": result.status, "rejected_invoice": previous_invoice, "note": payload.note},
        )
        self.db.commit()
        return self.get_result(result.id)

    # ================================================================== helpers

    def _lock_result(self, result_id: uuid.UUID) -> ReconciliationResult:
        result = self.repo.get_result(result_id, for_update=True)
        if result is None:
            raise NotFoundError("Reconciliation result not found")
        return result

    @staticmethod
    def _append(existing: str | None, addition: str) -> str:
        return f"{existing}\n\n{addition}" if existing else addition

    @staticmethod
    def _view(payment: Payment) -> PaymentView:
        return PaymentView(
            id=str(payment.id),
            transaction_reference=payment.transaction_reference,
            payment_reference=payment.payment_reference,
            sender_name=payment.sender_name,
            currency=payment.currency,
            amount=payment.amount,
            transaction_date=payment.transaction_date,
        )

    @staticmethod
    def _to_result(payment: Payment, decision: Decision) -> ReconciliationResult:
        return ReconciliationResult(
            payment_id=payment.id,
            invoice_id=uuid.UUID(decision.invoice_id) if decision.invoice_id else None,
            status=decision.status,
            match_method=decision.method if decision.method != METHOD_NONE else None,
            confidence=decision.confidence,
            invoice_amount=decision.invoice_amount,
            previously_received=decision.previously_received,
            allocated_amount=decision.allocate,
            outstanding_after=decision.outstanding_after,
            explanation=decision.explanation,
            candidates=[
                {
                    "invoice_id": c.invoice_id,
                    "invoice_number": c.invoice_number,
                    "buyer_name": c.buyer_name,
                    "currency": c.currency,
                    "outstanding": str(c.outstanding),  # money as a string, never a float
                    "name_score": c.name_score,
                    "reason": c.reason,
                }
                for c in decision.candidates
            ],
            review_decision=ReviewDecision.NONE,
        )

    @staticmethod
    def _item(
        result: ReconciliationResult, payment: Payment, invoice_number: str | None, invoice_currency: str | None
    ) -> ReconciliationItem:
        return ReconciliationItem(
            id=result.id,
            payment_id=payment.id,
            transaction_reference=payment.transaction_reference,
            payment_reference=payment.payment_reference,
            sender_name=payment.sender_name,
            currency=payment.currency,
            payment_amount=payment.amount,
            transaction_date=payment.transaction_date,
            invoice_id=result.invoice_id,
            invoice_number=invoice_number,
            invoice_currency=invoice_currency,
            invoice_amount=result.invoice_amount,
            previously_received=result.previously_received,
            allocated_amount=result.allocated_amount,
            outstanding_after=result.outstanding_after,
            match_method=result.match_method,
            confidence=result.confidence,
            status=result.status,
            explanation=result.explanation,
            review_decision=result.review_decision,
            needs_review=result.status in NEEDS_ATTENTION and result.review_decision != ReviewDecision.APPROVED,
            created_at=result.created_at,
        )

