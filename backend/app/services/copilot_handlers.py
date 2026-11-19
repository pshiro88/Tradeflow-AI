"""Predefined handlers: one per intent (BRD FR-030 steps 2-4).

Each handler runs fixed queries, does any arithmetic in Python/SQL (ageing, balances, counts), and returns
  - `answer`: a complete deterministic answer, used as-is when the AI is unavailable or fails validation
  - `facts`:  a compact, JSON-safe object: the ONLY thing the model is shown, and what its wording is checked against
  - `table`/`sources`: the underlying records for the user to inspect
The model never fetches, calculates or decides anything.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.enums import DocumentStatus, InvoiceStatus, ReconciliationStatus
from app.repositories.compliance_repository import ComplianceRepository
from app.repositories.copilot_repository import CopilotRepository
from app.schemas.ai import AnswerTable, SourceRef, TableColumn
from app.schemas.invoice import InvoiceFilters
from app.schemas.payment import PaymentFilters
from app.services.compliance_rules import ALWAYS_REQUIRED, DocState, ManualCheck, effective_status
from app.services.copilot_intents import Intent, IntentMatch
from app.services.invoice_service import InvoiceService
from app.services.payment_service import PaymentService
from app.services.reconciliation_service import ReconciliationService

MAX_ROWS = 15
MAX_LISTED_IN_ANSWER = 5

# What a question needs access to. Payment data is Finance-only everywhere else in the app, so it is here too.
FINANCE_ONLY = frozenset(
    {
        Intent.UNRECONCILED_PAYMENTS,
        Intent.DISCREPANCY_SUMMARY,
        Intent.TOP_OUTSTANDING_BUYERS,
        Intent.EXPLAIN_INVOICE,
        Intent.EXPLAIN_TRANSACTION,
    }
)


@dataclass
class HandlerResult:
    intent: Intent
    answer: str
    facts: dict[str, Any]
    table: AnswerTable | None = None
    sources: list[SourceRef] = field(default_factory=list)
    empty: bool = False  # nothing found: no point asking the model to word it


def money(amount: Decimal | str, currency: str) -> str:
    return f"{currency} {Decimal(str(amount)):,.2f}"


def _more(total: int, shown: int) -> str:
    return f", and {total - shown} more" if total > shown else ""


def _invoice_source(invoice_id: Any, number: str) -> SourceRef:
    return SourceRef(type="invoice", label=number, path=f"/invoices/{invoice_id}")


class CopilotHandlers:
    def __init__(self, db: Session, today: date) -> None:
        self.db = db
        self.today = today
        self.repo = CopilotRepository(db, today)
        self.invoices = InvoiceService(db)

    def run(self, match: IntentMatch) -> HandlerResult:
        handler = {
            Intent.OVERDUE_INVOICES: self.overdue_invoices,
            Intent.PENDING_AGEING: self.pending_ageing,
            Intent.UNRECONCILED_PAYMENTS: self.unreconciled_payments,
            Intent.DISCREPANCY_SUMMARY: self.discrepancy_summary,
            Intent.TOP_OUTSTANDING_BUYERS: self.top_outstanding_buyers,
            Intent.MISSING_DOCUMENTS: self.missing_documents,
            Intent.EXPLAIN_INVOICE: self.explain_invoice,
            Intent.EXPLAIN_TRANSACTION: self.explain_transaction,
        }[match.intent]
        return handler(**match.params)

    # ------------------------------------------------------------------ invoices

    def overdue_invoices(self) -> HandlerResult:
        page = self.invoices.list_invoices(
            InvoiceFilters(status=InvoiceStatus.OVERDUE), page=1, page_size=MAX_ROWS, sort_by="due_date", sort_dir="asc",
            today=self.today,
        )
        items = [
            {
                "invoice": i.invoice_number, "buyer": i.buyer_name, "due_date": i.due_date.isoformat(),
                "days_overdue": (self.today - i.due_date).days, "outstanding": money(i.outstanding_amount, i.currency),
            }
            for i in page.items
        ]
        if not items:
            return HandlerResult(Intent.OVERDUE_INVOICES, "No invoices are overdue.", {"count": 0}, empty=True)
        listed = "; ".join(f"{r['invoice']} ({r['buyer']}, {r['outstanding']} outstanding, {r['days_overdue']} days overdue)" for r in items[:MAX_LISTED_IN_ANSWER])
        return HandlerResult(
            Intent.OVERDUE_INVOICES,
            f"{page.total} invoice{'s are' if page.total != 1 else ' is'} overdue: {listed}{_more(page.total, min(page.total, MAX_LISTED_IN_ANSWER))}.",
            {"count": page.total, "invoices": items},
            AnswerTable(
                title="Overdue invoices",
                columns=[TableColumn(key="invoice", label="Invoice"), TableColumn(key="buyer", label="Buyer"),
                         TableColumn(key="due_date", label="Due date"), TableColumn(key="days_overdue", label="Days overdue", align="right"),
                         TableColumn(key="outstanding", label="Outstanding", align="right")],
                rows=[{k: str(v) for k, v in r.items()} for r in items],
            ),
            [_invoice_source(i.id, i.invoice_number) for i in page.items],
        )

    def pending_ageing(self, days: int) -> HandlerResult:
        """Invoices with a balance whose age (today - invoice date) exceeds `days`. Ageing is calculated in Python."""
        open_invoices = []
        for status in (InvoiceStatus.OPEN, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.OVERDUE):
            open_invoices += self.invoices.list_invoices(
                InvoiceFilters(status=status), page=1, page_size=100, sort_by="invoice_date", sort_dir="asc", today=self.today
            ).items
        aged = [((self.today - i.invoice_date).days, i) for i in open_invoices if (self.today - i.invoice_date).days > days]
        # Oldest first; ties broken by invoice number (invoice objects themselves are never compared).
        aged.sort(key=lambda pair: (-pair[0], pair[1].invoice_number))
        if not aged:
            return HandlerResult(
                Intent.PENDING_AGEING, f"No invoices have been pending for more than {days} days.",
                {"threshold_days": days, "count": 0}, empty=True,
            )
        items = [
            {"invoice": i.invoice_number, "buyer": i.buyer_name, "age_days": age, "status": i.status.value,
             "outstanding": money(i.outstanding_amount, i.currency)}
            for age, i in aged[:MAX_ROWS]
        ]
        listed = "; ".join(f"{r['invoice']} ({r['age_days']} days, {r['outstanding']} outstanding)" for r in items[:MAX_LISTED_IN_ANSWER])
        return HandlerResult(
            Intent.PENDING_AGEING,
            f"{len(aged)} invoice{'s have' if len(aged) != 1 else ' has'} been pending for more than {days} days (age is counted from the invoice date): {listed}{_more(len(aged), min(len(aged), MAX_LISTED_IN_ANSWER))}.",
            {"threshold_days": days, "count": len(aged), "invoices": items},
            AnswerTable(
                title=f"Invoices pending for more than {days} days",
                columns=[TableColumn(key="invoice", label="Invoice"), TableColumn(key="buyer", label="Buyer"),
                         TableColumn(key="age_days", label="Age (days)", align="right"), TableColumn(key="status", label="Status"),
                         TableColumn(key="outstanding", label="Outstanding", align="right")],
                rows=[{k: str(v) for k, v in r.items()} for r in items],
            ),
            [_invoice_source(i.id, i.invoice_number) for _, i in aged[:MAX_ROWS]],
        )

    def top_outstanding_buyers(self) -> HandlerResult:
        """Largest outstanding balances, ranked WITHIN each currency (different currencies are never added)."""
        by_currency: dict[str, list[tuple[str, Decimal, int]]] = defaultdict(list)
        for buyer, currency, outstanding, count in self.repo.outstanding_by_buyer():
            by_currency[currency].append((buyer, outstanding, count))
        if not by_currency:
            return HandlerResult(Intent.TOP_OUTSTANDING_BUYERS, "No buyer has an outstanding balance.", {"count": 0}, empty=True)

        top = {c: sorted(rows, key=lambda r: -r[1])[:3] for c, rows in by_currency.items()}
        facts = {
            "note": "ranked within each currency; currencies are not added together",
            "by_currency": {
                c: [{"buyer": b, "outstanding": money(o, c), "open_invoices": n} for b, o, n in rows] for c, rows in top.items()
            },
        }
        sentences = [
            f"In {c}: " + ", ".join(f"{b} ({money(o, c)})" for b, o, _ in rows) for c, rows in top.items()
        ]
        table_rows = [
            {"currency": c, "buyer": b, "outstanding": money(o, c), "open_invoices": str(n)}
            for c, rows in top.items() for b, o, n in rows
        ]
        return HandlerResult(
            Intent.TOP_OUTSTANDING_BUYERS,
            "Highest outstanding balances by currency (not added across currencies). " + "; ".join(sentences) + ".",
            facts,
            AnswerTable(
                title="Highest outstanding balances",
                columns=[TableColumn(key="currency", label="Currency"), TableColumn(key="buyer", label="Buyer"),
                         TableColumn(key="outstanding", label="Outstanding", align="right"),
                         TableColumn(key="open_invoices", label="Open invoices", align="right")],
                rows=table_rows,
            ),
        )

    def missing_documents(self) -> HandlerResult:
        # Same rules as the compliance checklist: a verified document counts, else the latest manual review,
        # else the uploaded documents. Only the always-required export documents are asked about here.
        required = [t.value for t in ALWAYS_REQUIRED]
        compliance = ComplianceRepository(self.db, self.today)
        issued = [inv for inv, _, _ in compliance.issued_invoices()]
        docs = compliance.documents_for([inv.id for inv in issued])
        checks = compliance.latest_checks([inv.id for inv in issued])
        missing = []
        for inv in issued:
            gaps = []
            for doc_type in ALWAYS_REQUIRED:
                states = [
                    DocState(id=str(d.id), file_name=d.file_name, verification_status=d.verification_status)
                    for d in docs.get(inv.id, []) if d.document_type == doc_type
                ]
                stored = checks.get((inv.id, doc_type.value))
                manual = ManualCheck(stored[0].status, stored[0].remarks, stored[1], stored[0].created_at) if stored else None
                if effective_status(states, manual)[0] in (DocumentStatus.NOT_UPLOADED, DocumentStatus.REJECTED):
                    gaps.append(doc_type.value)
            if gaps:
                missing.append((inv, gaps))
        if not missing:
            return HandlerResult(Intent.MISSING_DOCUMENTS, "Every issued invoice has all required supporting documents.", {"count": 0}, empty=True)
        items = [
            {"invoice": inv.invoice_number, "buyer": inv.buyer.buyer_name, "missing": ", ".join(t.replace("_", " ").title() for t in m)}
            for inv, m in missing[:MAX_ROWS]
        ]
        listed = "; ".join(f"{r['invoice']} lacks {r['missing']}" for r in items[:3])
        return HandlerResult(
            Intent.MISSING_DOCUMENTS,
            f"{len(missing)} issued invoice{'s are' if len(missing) != 1 else ' is'} missing at least one supporting document "
            f"(expected: {', '.join(t.replace('_', ' ').title() for t in required)}). For example: {listed}.",
            {"count": len(missing), "expected_documents": required, "invoices": items},
            AnswerTable(
                title="Invoices with missing supporting documents",
                columns=[TableColumn(key="invoice", label="Invoice"), TableColumn(key="buyer", label="Buyer"), TableColumn(key="missing", label="Missing")],
                rows=items,
            ),
            [_invoice_source(inv.id, inv.invoice_number) for inv, _ in missing[:MAX_ROWS]],
        )

    def explain_invoice(self, invoice_number: str) -> HandlerResult:
        invoice = self.invoices.repo.find_by_number(invoice_number)
        if invoice is None:
            return HandlerResult(
                Intent.EXPLAIN_INVOICE, f"I couldn't find an invoice numbered {invoice_number}.",
                {"not_found": invoice_number}, empty=True,
            )
        d = self.invoices.get_invoice(invoice.id, self.today)
        cur = d.currency
        payments = [
            {"transaction": p.transaction_reference, "amount": money(p.allocated_amount, cur), "date": p.transaction_date.isoformat(), "type": p.allocation_type.value}
            for p in d.payments
        ]
        days_to_due = (d.due_date - self.today).days
        due_text = f"due on {d.due_date.isoformat()} ({'in ' + str(days_to_due) + ' days' if days_to_due > 0 else 'today' if days_to_due == 0 else str(-days_to_due) + ' days ago'})"
        if d.status == InvoiceStatus.PAID:
            why = f"fully paid: {money(d.amount_received, cur)} received against {money(d.total_amount, cur)}."
        elif d.status == InvoiceStatus.PARTIALLY_PAID:
            why = f"partially paid: {money(d.amount_received, cur)} of {money(d.total_amount, cur)} has been received, leaving {money(d.outstanding_amount, cur)} outstanding, {due_text}."
        elif d.status == InvoiceStatus.OVERDUE:
            received = f" Only {money(d.amount_received, cur)} has been received." if d.has_payments else " No payment has been received."
            why = f"overdue: it was {due_text} and {money(d.outstanding_amount, cur)} of {money(d.total_amount, cur)} is still outstanding.{received}"
        elif d.status == InvoiceStatus.OPEN:
            why = f"open: no payment has been received yet and it is {due_text}; {money(d.outstanding_amount, cur)} is outstanding."
        else:
            why = f"{d.status.value.lower()}."
        pay_text = f" Payments applied: {', '.join(f'{p['transaction']} ({p['amount']})' for p in payments)}." if payments else ""
        facts = {
            "invoice": d.invoice_number, "buyer": d.buyer_name, "status": d.status.value, "total": money(d.total_amount, cur),
            "received": money(d.amount_received, cur), "outstanding": money(d.outstanding_amount, cur),
            "due_date": d.due_date.isoformat(), "days_overdue": max((self.today - d.due_date).days, 0), "payments": payments,
        }
        return HandlerResult(
            Intent.EXPLAIN_INVOICE, f"{d.invoice_number} ({d.buyer_name}) is {why}{pay_text}", facts,
            AnswerTable(
                title=f"Payments applied to {d.invoice_number}",
                columns=[TableColumn(key="transaction", label="Transaction"), TableColumn(key="date", label="Date"),
                         TableColumn(key="type", label="Type"), TableColumn(key="amount", label="Allocated", align="right")],
                rows=payments,
            ) if payments else None,
            [_invoice_source(d.id, d.invoice_number)],
        )

    # ------------------------------------------------------------------ payments and reconciliation

    def unreconciled_payments(self) -> HandlerResult:
        statuses = (ReconciliationStatus.PENDING, ReconciliationStatus.UNMATCHED, ReconciliationStatus.MISMATCH, ReconciliationStatus.MANUAL_REVIEW)
        service = PaymentService(self.db)
        counts: dict[str, int] = {}
        items: list[dict[str, str]] = []
        for status in statuses:
            page = service.list_payments(PaymentFilters(status=status), page=1, page_size=MAX_ROWS, sort_by="transaction_date", sort_dir="desc")
            if page.total:
                counts[status.value] = page.total
            items += [
                {"transaction": p.transaction_reference, "sender": p.sender_name, "amount": money(p.amount, p.currency),
                 "date": p.transaction_date.isoformat(), "status": status.value}
                for p in page.items
            ]
        total = sum(counts.values())
        if total == 0:
            return HandlerResult(Intent.UNRECONCILED_PAYMENTS, "Every payment has been reconciled.", {"count": 0}, empty=True)
        items = items[:MAX_ROWS]
        breakdown = ", ".join(f"{n} {s.replace('_', ' ').lower()}" for s, n in counts.items())
        listed = "; ".join(f"{r['transaction']} ({r['sender']}, {r['amount']})" for r in items[:MAX_LISTED_IN_ANSWER])
        return HandlerResult(
            Intent.UNRECONCILED_PAYMENTS,
            f"{total} payment{'s have' if total != 1 else ' has'} not been fully reconciled ({breakdown}). Latest: {listed}{_more(total, min(total, MAX_LISTED_IN_ANSWER))}.",
            {"count": total, "by_status": counts, "payments": items},
            AnswerTable(
                title="Payments not yet reconciled",
                columns=[TableColumn(key="transaction", label="Transaction"), TableColumn(key="sender", label="Sender"),
                         TableColumn(key="date", label="Date"), TableColumn(key="status", label="Status"),
                         TableColumn(key="amount", label="Amount", align="right")],
                rows=items,
            ),
            [SourceRef(type="reconciliation", label=r["transaction"], path=f"/reconciliation?q={r['transaction']}") for r in items],
        )

    def discrepancy_summary(self, period: str = "all") -> HandlerResult:
        start, end, label = None, None, "overall"
        if period == "this_month":
            start, end, label = self.today.replace(day=1), self.today, "this month"
        elif period == "last_month":
            end = self.today.replace(day=1) - timedelta(days=1)
            start, label = end.replace(day=1), "last month"
        counts, rows = self.repo.discrepancies(start, end, MAX_ROWS)
        total = sum(counts.values())
        if total == 0:
            return HandlerResult(
                Intent.DISCREPANCY_SUMMARY, f"No payment discrepancies were found {label}.", {"period": label, "count": 0}, empty=True
            )
        items = [
            {"transaction": p.transaction_reference, "sender": p.sender_name, "amount": money(p.amount, p.currency),
             "date": p.transaction_date.isoformat(), "status": r.status.value, "invoice": number or "none", "why": (r.explanation or "").split(". ")[0]}
            for p, r, number in rows
        ]
        breakdown = ", ".join(f"{n} {s.value.replace('_', ' ').lower()}" for s, n in sorted(counts.items(), key=lambda kv: -kv[1]))
        return HandlerResult(
            Intent.DISCREPANCY_SUMMARY,
            f"{total} payment discrepanc{'ies were' if total != 1 else 'y was'} found {label}: {breakdown}.",
            {"period": label, "count": total, "by_status": {s.value: n for s, n in counts.items()}, "payments": items},
            AnswerTable(
                title=f"Payment discrepancies ({label})",
                columns=[TableColumn(key="transaction", label="Transaction"), TableColumn(key="sender", label="Sender"),
                         TableColumn(key="date", label="Date"), TableColumn(key="status", label="Status"),
                         TableColumn(key="amount", label="Amount", align="right")],
                rows=[{k: v for k, v in r.items() if k not in ("why", "invoice")} for r in items],
            ),
            [SourceRef(type="reconciliation", label=r["transaction"], path=f"/reconciliation?q={r['transaction']}") for r in items],
        )

    def explain_transaction(self, transaction_reference: str) -> HandlerResult:
        found = self.repo.result_for_transaction(transaction_reference)
        if found is None:
            return HandlerResult(
                Intent.EXPLAIN_TRANSACTION, f"I couldn't find a transaction {transaction_reference}.",
                {"not_found": transaction_reference}, empty=True,
            )
        result_id, payment = found
        ref = payment.transaction_reference
        source = SourceRef(type="reconciliation", label=ref, path=f"/reconciliation?q={ref}")
        if result_id is None:
            return HandlerResult(
                Intent.EXPLAIN_TRANSACTION,
                f"{ref} ({money(payment.amount, payment.currency)} from {payment.sender_name}) has not been reconciled yet. Run reconciliation to process it.",
                {"transaction": ref, "status": "PENDING"}, sources=[source], empty=True,
            )
        d = ReconciliationService(self.db).get_result(result_id)
        facts = {
            "transaction": ref, "sender": d.sender_name, "payment": money(d.payment_amount, d.currency),
            "status": d.status.value, "invoice": d.invoice_number or "none", "method": d.match_method or "none",
            "allocated": money(d.allocated_amount, d.currency), "explanation": d.explanation,
            "reviewed_by": d.reviewed_by_name or "nobody", "review_note": d.review_note or "",
        }
        return HandlerResult(
            Intent.EXPLAIN_TRANSACTION,
            f"{ref} ({money(d.payment_amount, d.currency)} from {d.sender_name}) is {d.status.value.replace('_', ' ').lower()}. {d.explanation}",
            facts, sources=[source],
        )
