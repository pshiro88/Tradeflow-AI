"""Deterministic payment reconciliation engine (BRD module 5).

PURE LOGIC: no database, no HTTP, no clock, no randomness, no AI. Callers pass plain data in and get a
`Decision` back, so every rule below is unit-testable and the same input always gives the same output.

Order of evaluation for one payment
-----------------------------------
 0. DUPLICATE   Another, already-processed payment has the same reference, sender, currency, amount
                and date under a different transaction reference (the bank sent it twice).
 1. Reference   The payment reference must equal an invoice number (case/space-insensitive).
 2. Currency    Payment and invoice currency must match. Amounts are NEVER compared across currencies.
 3. Buyer name  RapidFuzz similarity between sender and buyer. It can only *block or escalate* a match;
                it can never create one on its own.
 4. Amount      outstanding = invoice total - previously allocated. Compare payment to outstanding:
                  equal -> MATCHED, smaller -> PARTIAL, larger -> MANUAL_REVIEW (never over-allocate).

Safety principle: whenever the identity of the payer or the invoice is uncertain, the engine refuses to
allocate and escalates to MANUAL_REVIEW. Allocation only happens on an exact reference match with a
compatible currency and a convincing buyer name. All money is `Decimal`.
"""

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from rapidfuzz import fuzz

from app.models.enums import ReconciliationStatus

# ---- tunable thresholds (0-100 similarity scores) -------------------------------------------------
NAME_MATCH_MIN = 85  # at or above: the sender is accepted as the buyer
NAME_CONFLICT_BELOW = 60  # below: the sender is a different company -> MISMATCH
# between the two: loosely similar -> a human must confirm (MANUAL_REVIEW)

# Confidence is an estimate shown to reviewers, not a probability.
REFERENCE_BASE_CONFIDENCE = Decimal("70")  # exact reference alone
REFERENCE_NAME_WEIGHT = Decimal("0.30")  # name similarity adds up to 30 points -> max 100
FALLBACK_CONFIDENCE_FACTOR = Decimal("0.80")  # name+amount without a reference is capped at 80
MAX_HINT_CANDIDATES = 3

METHOD_EXACT_REFERENCE = "EXACT_REFERENCE"
METHOD_NAME_AND_AMOUNT = "NAME_AND_AMOUNT"
METHOD_DUPLICATE = "DUPLICATE_SIGNATURE"
METHOD_NONE = "NONE"

CENT = Decimal("0.01")

_LEGAL_SUFFIXES = frozenset(
    {"llc", "ltd", "limited", "gmbh", "sas", "fze", "fzco", "inc", "corp", "corporation", "co", "company",
     "pvt", "plc", "ag", "bv", "sa", "llp", "the"}
)


# ---- input / output data ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InvoiceState:
    """An invoice as the engine sees it. `allocated` = money already applied before this payment."""

    id: str
    invoice_number: str
    buyer_name: str
    currency: str
    total_amount: Decimal
    allocated: Decimal
    payable: bool  # False for DRAFT / CANCELLED invoices
    status_label: str = ""

    @property
    def outstanding(self) -> Decimal:
        return self.total_amount - self.allocated


@dataclass(frozen=True)
class PaymentView:
    id: str
    transaction_reference: str
    payment_reference: str | None
    sender_name: str
    currency: str
    amount: Decimal
    transaction_date: object  # datetime.date; only compared for equality


@dataclass(frozen=True)
class Candidate:
    invoice_id: str
    invoice_number: str
    buyer_name: str
    currency: str
    outstanding: Decimal
    name_score: int
    reason: str


@dataclass(frozen=True)
class Decision:
    status: ReconciliationStatus
    method: str
    explanation: str
    invoice_id: str | None = None
    allocate: Decimal = Decimal("0.00")
    confidence: Decimal | None = None
    invoice_amount: Decimal | None = None
    previously_received: Decimal | None = None
    outstanding_after: Decimal | None = None
    candidates: tuple[Candidate, ...] = field(default_factory=tuple)


# ---- text helpers ------------------------------------------------------------------------------------


def normalise_reference(value: str | None) -> str:
    """Case-, space- and surrounding-whitespace-insensitive form of a payment/invoice reference."""
    return re.sub(r"\s+", "", value or "").upper()


def normalise_name(value: str | None) -> str:
    """Lower-case, accent-free, punctuation-free company name without legal suffixes (LLC, Ltd, GmbH ...)."""
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower().replace("&", " and ")
    # "L.L.C." / "S.A.S." -> "llc" / "sas" so dotted legal suffixes are recognised and dropped.
    text = re.sub(r"(?<![a-z])((?:[a-z]\.){2,})", lambda m: m.group(1).replace(".", ""), text)
    tokens = [t for t in re.split(r"[^a-z0-9]+", text) if t and t not in _LEGAL_SUFFIXES]
    return " ".join(tokens)


def name_similarity(sender: str | None, buyer: str | None) -> int:
    """0-100 similarity of two company names (word-order and legal-suffix insensitive)."""
    a, b = normalise_name(sender), normalise_name(buyer)
    if not a or not b:
        return 0
    return round(fuzz.token_sort_ratio(a, b))


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _fmt(amount: Decimal, currency: str) -> str:
    return f"{currency} {amount:,.2f}"


def _confidence_for_reference(name_score: int) -> Decimal:
    return money(min(Decimal("100"), REFERENCE_BASE_CONFIDENCE + REFERENCE_NAME_WEIGHT * name_score))


def _candidate(inv: InvoiceState, score: int, reason: str) -> Candidate:
    return Candidate(
        invoice_id=inv.id,
        invoice_number=inv.invoice_number,
        buyer_name=inv.buyer_name,
        currency=inv.currency,
        outstanding=money(inv.outstanding),
        name_score=score,
        reason=reason,
    )


# ---- the engine --------------------------------------------------------------------------------------


def find_duplicate(payment: PaymentView, processed: Sequence[PaymentView]) -> PaymentView | None:
    """An earlier payment with an identical signature but a different transaction reference."""
    reference = normalise_reference(payment.payment_reference)
    if not reference:
        return None  # identical same-day payments without any reference are not safely 'duplicates'
    sender = normalise_name(payment.sender_name)
    for other in processed:
        if (
            other.id != payment.id
            and other.transaction_reference != payment.transaction_reference
            and normalise_reference(other.payment_reference) == reference
            and other.currency == payment.currency
            and other.amount == payment.amount
            and other.transaction_date == payment.transaction_date
            and normalise_name(other.sender_name) == sender
        ):
            return other
    return None


def reconcile_payment(
    payment: PaymentView,
    invoices: Mapping[str, InvoiceState],
    processed: Sequence[PaymentView],
) -> Decision:
    """Decide the outcome for one payment.

    `invoices` maps invoice id -> current state (including allocations made earlier in the same run).
    `processed` holds payments that were already reconciled (used only for duplicate detection).
    """
    duplicate = find_duplicate(payment, processed)
    if duplicate is not None:
        return Decision(
            status=ReconciliationStatus.DUPLICATE,
            method=METHOD_DUPLICATE,
            explanation=(
                f"Identical to {duplicate.transaction_reference}: same reference, sender, currency, amount and date "
                f"({_fmt(payment.amount, payment.currency)}), but a different transaction reference. "
                "It looks like the bank sent this payment twice, so nothing was allocated."
            ),
        )

    reference = normalise_reference(payment.payment_reference)
    by_number = {normalise_reference(inv.invoice_number): inv for inv in invoices.values()}
    invoice = by_number.get(reference) if reference else None

    if invoice is not None:
        return _reconcile_against_reference(payment, invoice)
    return _reconcile_without_reference(payment, list(invoices.values()), reference)


def _reconcile_against_reference(payment: PaymentView, invoice: InvoiceState) -> Decision:
    outstanding = money(invoice.outstanding)
    base = {
        "invoice_id": invoice.id,
        "invoice_amount": money(invoice.total_amount),
        "previously_received": money(invoice.allocated),
        "outstanding_after": outstanding,  # unchanged unless we allocate below
    }
    name_score = name_similarity(payment.sender_name, invoice.buyer_name)
    candidate = (_candidate(invoice, name_score, "Payment reference matches this invoice"),)

    # The referenced invoice cannot take money at all.
    if not invoice.payable:
        state = invoice.status_label.lower() or "not payable"
        return Decision(
            status=ReconciliationStatus.MISMATCH,
            method=METHOD_EXACT_REFERENCE,
            explanation=f"Reference {invoice.invoice_number} matches an invoice, but that invoice is {state} and cannot receive payments.",
            candidates=candidate,
            **base,
        )

    # Level 2 - currency: never compare amounts across currencies.
    if payment.currency != invoice.currency:
        return Decision(
            status=ReconciliationStatus.MISMATCH,
            method=METHOD_EXACT_REFERENCE,
            explanation=(
                f"Reference {invoice.invoice_number} matches, but the payment is in {payment.currency} and the "
                f"invoice is in {invoice.currency}. Amounts are not compared across currencies without an "
                "explicit conversion, so nothing was allocated."
            ),
            candidates=candidate,
            **base,
        )

    # Level 3 - buyer name: a clearly different sender blocks the match.
    if name_score < NAME_CONFLICT_BELOW:
        return Decision(
            status=ReconciliationStatus.MISMATCH,
            method=METHOD_EXACT_REFERENCE,
            explanation=(
                f"Reference {invoice.invoice_number} matches, but the sender '{payment.sender_name}' does not "
                f"resemble the buyer '{invoice.buyer_name}' (name similarity {name_score}/100). "
                "Nothing was allocated."
            ),
            candidates=candidate,
            **base,
        )

    confidence = _confidence_for_reference(name_score)

    if outstanding <= 0:
        return Decision(
            status=ReconciliationStatus.MANUAL_REVIEW,
            method=METHOD_EXACT_REFERENCE,
            explanation=(
                f"Invoice {invoice.invoice_number} is already fully settled, so this "
                f"{_fmt(payment.amount, payment.currency)} payment may be an overpayment or misapplied. "
                "A person must decide how to treat it."
            ),
            confidence=confidence,
            candidates=candidate,
            **base,
        )

    if name_score < NAME_MATCH_MIN:
        return Decision(
            status=ReconciliationStatus.MANUAL_REVIEW,
            method=METHOD_EXACT_REFERENCE,
            explanation=(
                f"Reference {invoice.invoice_number} matches, but the sender '{payment.sender_name}' only loosely "
                f"resembles the buyer '{invoice.buyer_name}' (name similarity {name_score}/100). "
                "A person must confirm before any money is allocated."
            ),
            confidence=confidence,
            candidates=candidate,
            **base,
        )

    # Level 4 - amount against the outstanding balance.
    if payment.amount > outstanding:
        excess = money(payment.amount - outstanding)
        return Decision(
            status=ReconciliationStatus.MANUAL_REVIEW,
            method=METHOD_EXACT_REFERENCE,
            explanation=(
                f"Payment of {_fmt(payment.amount, payment.currency)} exceeds the outstanding "
                f"{_fmt(outstanding, invoice.currency)} on {invoice.invoice_number} by {_fmt(excess, invoice.currency)}. "
                "The engine never over-allocates, so a person must decide what to do with the excess."
            ),
            confidence=confidence,
            candidates=candidate,
            **base,
        )

    after = money(outstanding - payment.amount)
    base["outstanding_after"] = after
    if after == 0:
        return Decision(
            status=ReconciliationStatus.MATCHED,
            method=METHOD_EXACT_REFERENCE,
            explanation=(
                f"Reference, currency and buyer all match. {_fmt(payment.amount, payment.currency)} settles "
                f"{invoice.invoice_number} in full."
            ),
            allocate=money(payment.amount),
            confidence=confidence,
            candidates=candidate,
            **base,
        )
    return Decision(
        status=ReconciliationStatus.PARTIAL,
        method=METHOD_EXACT_REFERENCE,
        explanation=(
            f"Reference, currency and buyer all match. {_fmt(payment.amount, payment.currency)} was allocated to "
            f"{invoice.invoice_number}; {_fmt(after, invoice.currency)} of "
            f"{_fmt(money(invoice.total_amount), invoice.currency)} is still outstanding."
        ),
        allocate=money(payment.amount),
        confidence=confidence,
        candidates=candidate,
        **base,
    )


def _reconcile_without_reference(payment: PaymentView, invoices: list[InvoiceState], reference: str) -> Decision:
    """No usable reference: look for invoices where BOTH the buyer name and the exact amount agree."""
    why = (
        "The payment has no reference."
        if not reference
        else f"Reference '{payment.payment_reference}' does not match any invoice."
    )
    open_same_currency = [i for i in invoices if i.payable and i.currency == payment.currency and i.outstanding > 0]
    scored = sorted(
        ((name_similarity(payment.sender_name, i.buyer_name), i) for i in open_same_currency),
        key=lambda pair: (-pair[0], pair[1].invoice_number),
    )
    similar_name = [(score, inv) for score, inv in scored if score >= NAME_MATCH_MIN]
    exact = [(score, inv) for score, inv in similar_name if money(inv.outstanding) == money(payment.amount)]

    if exact:
        candidates = tuple(
            _candidate(inv, score, "Buyer name is similar and the amount equals the outstanding balance")
            for score, inv in exact
        )
        best_score, best = exact[0]
        confidence = money(FALLBACK_CONFIDENCE_FACTOR * best_score)
        if len(exact) == 1:
            return Decision(
                status=ReconciliationStatus.MANUAL_REVIEW,
                method=METHOD_NAME_AND_AMOUNT,
                explanation=(
                    f"{why} The sender '{payment.sender_name}' resembles the buyer of {best.invoice_number} "
                    f"(similarity {best_score}/100) and {_fmt(payment.amount, payment.currency)} equals its "
                    "outstanding balance. Name and amount alone are not enough to allocate automatically, so a "
                    "person must confirm."
                ),
                invoice_id=best.id,
                confidence=confidence,
                invoice_amount=money(best.total_amount),
                previously_received=money(best.allocated),
                outstanding_after=money(best.outstanding),
                candidates=candidates,
            )
        return Decision(
            status=ReconciliationStatus.MANUAL_REVIEW,
            method=METHOD_NAME_AND_AMOUNT,
            explanation=(
                f"{why} {len(exact)} invoices ({', '.join(c.invoice_number for c in candidates)}) have a similar "
                f"buyer name and an outstanding balance equal to {_fmt(payment.amount, payment.currency)}. "
                "The match is ambiguous, so a person must choose."
            ),
            confidence=confidence,
            candidates=candidates,
        )

    hints = tuple(
        _candidate(inv, score, "Buyer name is similar but the amount does not match the outstanding balance")
        for score, inv in similar_name[:MAX_HINT_CANDIDATES]
    )
    extra = (
        " The sender resembles a buyer with open invoices, but no outstanding amount equals the payment."
        if hints
        else ""
    )
    return Decision(
        status=ReconciliationStatus.UNMATCHED,
        method=METHOD_NONE,
        explanation=f"{why} No reliable invoice candidate was found.{extra}",
        candidates=hints,
    )
