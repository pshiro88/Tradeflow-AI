"""Compare what a document says against the invoice it belongs to (BRD FR-028).

Pure logic, deterministic: the model plays no part. A finding is a prompt for a person to look, never a
legal or regulatory judgement.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from app.services.reconciliation_engine import NAME_MATCH_MIN, name_similarity, normalise_reference

Status = Literal["MATCH", "MISMATCH", "NOT_COMPARABLE"]


@dataclass(frozen=True)
class InvoiceFacts:
    invoice_number: str
    exporter_name: str
    buyer_name: str
    currency: str
    total_amount: Decimal
    invoice_date: date
    due_date: date


@dataclass(frozen=True)
class Finding:
    field: str
    label: str
    status: Status
    document_value: str | None
    invoice_value: str
    message: str


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except InvalidOperation:
        return None


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def compare_with_invoice(fields: dict[str, Any], invoice: InvoiceFacts) -> list[Finding]:
    """`fields` is the extracted (or user-confirmed) data: strings for amounts and ISO dates."""
    findings: list[Finding] = []

    def add(field: str, label: str, doc: str | None, inv: str, matches: bool | None, mismatch_msg: str) -> None:
        if matches is None:
            findings.append(Finding(field, label, "NOT_COMPARABLE", doc, inv, f"{label} was not found in the document"))
        elif matches:
            findings.append(Finding(field, label, "MATCH", doc, inv, f"{label} matches the invoice"))
        else:
            findings.append(Finding(field, label, "MISMATCH", doc, inv, mismatch_msg))

    number = fields.get("invoice_number")
    add(
        "invoice_number", "Invoice number", number, invoice.invoice_number,
        None if not number else normalise_reference(number) == normalise_reference(invoice.invoice_number),
        f"Document says {number}, invoice is {invoice.invoice_number}",
    )

    for field, label, expected in (
        ("exporter_name", "Exporter", invoice.exporter_name),
        ("buyer_name", "Buyer", invoice.buyer_name),
    ):
        value = fields.get(field)
        add(
            field, label, value, expected,
            None if not value else name_similarity(value, expected) >= NAME_MATCH_MIN,
            f"Document says '{value}', invoice has '{expected}'",
        )

    currency = fields.get("currency")
    add(
        "currency", "Currency", currency, invoice.currency,
        None if not currency else currency.upper() == invoice.currency,
        f"Document is in {currency}, invoice is in {invoice.currency}",
    )

    amount = _decimal(fields.get("invoice_amount"))
    add(
        "invoice_amount", "Amount", None if amount is None else f"{amount:,.2f}", f"{invoice.total_amount:,.2f}",
        None if amount is None else amount == invoice.total_amount,
        f"Document total is {amount if amount is None else format(amount, ',.2f')}, invoice total is {invoice.total_amount:,.2f}",
    )

    for field, label, expected in (
        ("invoice_date", "Invoice date", invoice.invoice_date),
        ("due_date", "Due date", invoice.due_date),
    ):
        value = _date(fields.get(field))
        add(
            field, label, value.isoformat() if value else None, expected.isoformat(),
            None if value is None else value == expected,
            f"Document says {value}, invoice has {expected.isoformat()}",
        )
    return findings
