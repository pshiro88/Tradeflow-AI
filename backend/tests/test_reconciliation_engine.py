"""Unit tests for the pure reconciliation engine. No database, no HTTP.

Covers every scenario required by BRD FR-019 plus safety properties that must hold for any input.
"""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from itertools import count

import pytest

from app.models.enums import ReconciliationStatus as S
from app.services.reconciliation_engine import (
    InvoiceState,
    PaymentView,
    find_duplicate,
    name_similarity,
    normalise_name,
    normalise_reference,
    reconcile_payment,
)

D = Decimal
TODAY = date(2026, 11, 16)
_ids = count(1)


def inv(number="INV-1", buyer="Acme Imports LLC", currency="USD", total="10000.00", allocated="0.00", payable=True, status=""):
    return InvoiceState(
        id=f"inv-{number}", invoice_number=number, buyer_name=buyer, currency=currency,
        total_amount=D(total), allocated=D(allocated), payable=payable, status_label=status,
    )


def pay(txn="TXN-1", ref="INV-1", sender="Acme Imports LLC", currency="USD", amount="10000.00", day=TODAY):
    return PaymentView(
        id=f"pay-{txn}", transaction_reference=txn, payment_reference=ref, sender_name=sender,
        currency=currency, amount=D(amount), transaction_date=day,
    )


def decide(payment, *invoices, processed=()):
    return reconcile_payment(payment, {i.id: i for i in invoices}, list(processed))


def run_sequence(payments, invoices):
    """Process payments in order, applying each allocation to the invoice state like the service does."""
    state = {i.id: i for i in invoices}
    processed, decisions = [], []
    for p in payments:
        d = reconcile_payment(p, state, processed)
        decisions.append(d)
        if d.status != S.DUPLICATE:
            processed.append(p)
        if d.allocate > 0:
            target = state[d.invoice_id]
            state[target.id] = replace(target, allocated=target.allocated + d.allocate)
    return decisions, state


# ======================================================================== BRD acceptance scenarios


def test_exact_reference_match():
    d = decide(pay(), inv())
    assert d.status == S.MATCHED
    assert d.invoice_id == "inv-INV-1" and d.method == "EXACT_REFERENCE"


def test_full_payment_settles_invoice():
    d = decide(pay(amount="10000.00"), inv(total="10000.00"))
    assert d.status == S.MATCHED
    assert d.allocate == D("10000.00")
    assert d.previously_received == D("0.00") and d.outstanding_after == D("0.00")
    assert d.invoice_amount == D("10000.00")
    assert d.confidence == D("100.00")


def test_partial_payment():
    d = decide(pay(amount="6000.00"), inv(total="10000.00"))
    assert d.status == S.PARTIAL
    assert d.allocate == D("6000.00") and d.outstanding_after == D("4000.00")
    assert "4,000.00" in d.explanation


def test_multiple_partial_payments_then_settlement_brd_example():
    """INV-1024: 6,000 + 3,500 leaves 500 outstanding; a later 500 settles it (BRD FR-017)."""
    invoice = inv("INV-1024", total="10000.00")
    decisions, state = run_sequence(
        [pay("T1", "INV-1024", amount="6000.00"), pay("T2", "INV-1024", amount="3500.00"), pay("T3", "INV-1024", amount="500.00")],
        [invoice],
    )
    assert [d.status for d in decisions] == [S.PARTIAL, S.PARTIAL, S.MATCHED]
    assert decisions[1].previously_received == D("6000.00") and decisions[1].outstanding_after == D("500.00")
    assert decisions[2].previously_received == D("9500.00") and decisions[2].outstanding_after == D("0.00")
    assert state[invoice.id].allocated == D("10000.00")


def test_currency_mismatch_is_never_allocated():
    d = decide(pay(currency="EUR", amount="10000.00"), inv(currency="USD", total="10000.00"))
    assert d.status == S.MISMATCH
    assert d.allocate == 0
    assert "EUR" in d.explanation and "USD" in d.explanation


def test_currency_mismatch_ignores_amounts_entirely():
    """Same number or different number: the outcome and the allocation are identical."""
    same_number = decide(pay(currency="EUR", amount="10000.00"), inv(currency="USD"))
    smaller = decide(pay(currency="EUR", amount="1.00"), inv(currency="USD"))
    larger = decide(pay(currency="EUR", amount="99999.00"), inv(currency="USD"))
    assert {d.status for d in (same_number, smaller, larger)} == {S.MISMATCH}
    assert all(d.allocate == 0 for d in (same_number, smaller, larger))


def test_unknown_invoice_reference():
    d = decide(pay(ref="INV-9999", sender="Unknown Remitter Co", amount="123.00"), inv())
    assert d.status == S.UNMATCHED and d.allocate == 0 and d.invoice_id is None
    assert "INV-9999" in d.explanation


def test_missing_reference_is_unmatched_when_nothing_else_fits():
    d = decide(pay(ref=None, sender="Totally Unknown Co", amount="123.00"), inv())
    assert d.status == S.UNMATCHED and "no reference" in d.explanation.lower()


def test_duplicate_transaction():
    original = pay("TXN-1")
    resent = pay("TXN-2")  # same reference, sender, currency, amount and date; new transaction reference
    d = decide(resent, inv(), processed=[original])
    assert d.status == S.DUPLICATE and d.allocate == 0
    assert "TXN-1" in d.explanation


def test_overpayment_is_never_over_allocated():
    d = decide(pay(amount="12000.00"), inv(total="10000.00"))
    assert d.status == S.MANUAL_REVIEW
    assert d.allocate == 0
    assert "2,000.00" in d.explanation and "never over-allocates" in d.explanation


def test_overpayment_after_partial_payments():
    d = decide(pay(amount="600.00"), inv(total="10000.00", allocated="9500.00"))
    assert d.status == S.MANUAL_REVIEW and d.allocate == 0
    assert "100.00" in d.explanation


def test_ambiguous_buyer_match_requires_manual_review():
    """Reference matches but the sender only loosely resembles the buyer (score 60-84)."""
    assert 60 <= name_similarity("Noor Gulf Trading", "Al Noor General Trading LLC") < 85
    d = decide(pay(sender="Noor Gulf Trading"), inv(buyer="Al Noor General Trading LLC"))
    assert d.status == S.MANUAL_REVIEW and d.allocate == 0
    assert d.confidence is not None and d.confidence < D("100")


def test_conflicting_buyer_is_a_mismatch():
    assert name_similarity("Delta Retail Partners GmbH", "Acme Imports LLC") < 60
    d = decide(pay(sender="Delta Retail Partners GmbH"), inv())
    assert d.status == S.MISMATCH and d.allocate == 0
    assert "does not resemble" in d.explanation


# ======================================================================== other rules


@pytest.mark.parametrize("status_label", ["Cancelled", "Draft"])
def test_unpayable_invoice_is_a_mismatch(status_label):
    d = decide(pay(), inv(payable=False, status=status_label))
    assert d.status == S.MISMATCH and d.allocate == 0
    assert status_label.lower() in d.explanation


def test_payment_against_fully_settled_invoice_needs_review():
    d = decide(pay(amount="50.00"), inv(total="10000.00", allocated="10000.00"))
    assert d.status == S.MANUAL_REVIEW and d.allocate == 0
    assert "already fully settled" in d.explanation


def test_reference_matching_ignores_case_and_spaces():
    for ref in ("inv-1", " INV-1 ", "Inv - 1".replace(" - ", "-"), "I N V-1"):
        assert decide(pay(ref=ref), inv()).status == S.MATCHED, ref


def test_reference_must_match_exactly_not_partially():
    """A near-miss reference is never treated as a reference match, so it can never auto-allocate."""
    other = dict(sender="Unknown Remitter Co", amount="123.00")
    assert decide(pay(ref="INV-10", **other), inv("INV-1")).status == S.UNMATCHED
    assert decide(pay(ref="PAYMENT FOR INV-1", **other), inv("INV-1")).status == S.UNMATCHED
    # Even when buyer and amount agree, a mistyped reference only escalates to a human.
    typo = decide(pay(ref="INV-10"), inv("INV-1"))
    assert typo.allocate == 0 and typo.status == S.MANUAL_REVIEW and typo.method == "NAME_AND_AMOUNT"


def test_decimal_arithmetic_is_exact():
    """0.10 + 0.20 must settle 0.30 exactly (binary floats would leave a residue)."""
    decisions, state = run_sequence([pay("A", amount="0.10"), pay("B", amount="0.20")], [inv(total="0.30")])
    assert [d.status for d in decisions] == [S.PARTIAL, S.MATCHED]
    assert decisions[1].outstanding_after == D("0.00")


def test_confidence_scales_with_name_similarity():
    exact = decide(pay(sender="Acme Imports LLC"), inv())
    similar = decide(pay(sender="Acme Importers"), inv())
    assert exact.confidence == D("100.00")
    assert similar.status in (S.MATCHED, S.MANUAL_REVIEW)
    assert similar.confidence < exact.confidence


# ------------------------------------------------------------------------ fallback (no reference)


def test_no_reference_name_and_exact_amount_goes_to_manual_review_never_auto():
    invoice = inv("INV-7", buyer="Caledonia Retail Group Ltd", currency="GBP", total="9300.00")
    d = decide(pay(ref=None, sender="Caledonia Retail Group Limited", currency="GBP", amount="9300.00"), invoice)
    assert d.status == S.MANUAL_REVIEW and d.allocate == 0
    assert d.method == "NAME_AND_AMOUNT" and d.invoice_id == invoice.id
    assert D("0") < d.confidence <= D("80.00")  # fallback confidence is capped
    assert [c.invoice_number for c in d.candidates] == ["INV-7"]


def test_no_reference_ambiguous_candidates():
    a = inv("INV-A", buyer="Acme Imports LLC", total="500.00")
    b = inv("INV-B", buyer="Acme Imports LLC", total="500.00")
    d = decide(pay(ref=None, amount="500.00"), a, b)
    assert d.status == S.MANUAL_REVIEW and d.invoice_id is None
    assert {c.invoice_number for c in d.candidates} == {"INV-A", "INV-B"}
    assert "ambiguous" in d.explanation


def test_no_reference_similar_name_but_different_amount_is_unmatched_with_hint():
    d = decide(pay(ref="PO-77", amount="7750.00"), inv("INV-7", total="7800.00"))
    assert d.status == S.UNMATCHED and d.allocate == 0
    assert [c.invoice_number for c in d.candidates] == ["INV-7"]  # shown to the reviewer as a hint only


def test_no_reference_matching_amount_but_different_name_is_unmatched():
    d = decide(pay(ref=None, sender="Zenith Marine Exports Inc", amount="10000.00"), inv())
    assert d.status == S.UNMATCHED and d.candidates == ()


def test_fallback_never_considers_other_currencies():
    d = decide(pay(ref=None, currency="EUR", amount="10000.00"), inv(currency="USD", total="10000.00"))
    assert d.status == S.UNMATCHED and d.candidates == ()


def test_fallback_skips_unpayable_and_settled_invoices():
    settled = inv("INV-1", total="500.00", allocated="500.00")
    cancelled = inv("INV-2", total="500.00", payable=False)
    assert decide(pay(ref=None, amount="500.00"), settled, cancelled).status == S.UNMATCHED


# ------------------------------------------------------------------------ duplicate detection details


def test_duplicate_requires_every_attribute_to_agree():
    base = pay("TXN-1")
    for changed in (
        pay("TXN-2", amount="9999.00"),
        pay("TXN-2", day=TODAY - timedelta(days=1)),
        pay("TXN-2", currency="EUR"),
        pay("TXN-2", sender="Someone Else Ltd"),
        pay("TXN-2", ref="INV-2"),
    ):
        assert find_duplicate(changed, [base]) is None


def test_payments_without_a_reference_are_not_treated_as_duplicates():
    assert find_duplicate(pay("TXN-2", ref=None), [pay("TXN-1", ref=None)]) is None


def test_a_payment_is_never_a_duplicate_of_itself_or_its_own_reference():
    p = pay("TXN-1")
    assert find_duplicate(p, [p]) is None
    assert find_duplicate(pay("TXN-1"), [pay("TXN-1")]) is None  # same transaction reference = same record


def test_duplicate_detection_tolerates_cosmetic_name_differences():
    assert find_duplicate(pay("TXN-2", sender="ACME IMPORTS L.L.C."), [pay("TXN-1", sender="Acme Imports LLC")]) is not None


def test_duplicate_does_not_consume_invoice_balance():
    decisions, state = run_sequence([pay("T1", amount="4000.00"), pay("T2", amount="4000.00")], [inv(total="10000.00")])
    assert [d.status for d in decisions] == [S.PARTIAL, S.DUPLICATE]
    assert state["inv-INV-1"].allocated == D("4000.00")


# ------------------------------------------------------------------------ text helpers


def test_name_normalisation_and_similarity():
    assert normalise_name("Lumière Distribution S.A.S.") == "lumiere distribution"
    assert normalise_name("Harbor & Pine Trading Co") == "harbor and pine trading"
    assert name_similarity("Caledonia Retail Group Limited", "Caledonia Retail Group Ltd") == 100
    assert name_similarity("Harbor and Pine Trading Company", "Harbor & Pine Trading Co") == 100
    assert name_similarity("Pine Harbor Trading", "Harbor & Pine Trading Co") >= 85  # word order
    assert name_similarity("Delta Retail Partners GmbH", "Lumière Distribution SAS") < 60
    assert name_similarity("", "Acme") == 0 and name_similarity(None, None) == 0


def test_reference_normalisation():
    assert normalise_reference(" inv 1024 ") == "INV1024"
    assert normalise_reference(None) == ""


# ======================================================================== safety properties


AMOUNTS = ["0.01", "0.99", "100.00", "4999.99", "5000.00", "5000.01", "9999.99", "10000.00", "10000.01", "50000.00"]
ALLOCATED = ["0.00", "0.01", "5000.00", "9999.99", "10000.00"]


@pytest.mark.parametrize("amount", AMOUNTS)
@pytest.mark.parametrize("allocated", ALLOCATED)
@pytest.mark.parametrize("currency", ["USD", "EUR"])
@pytest.mark.parametrize("sender", ["Acme Imports LLC", "Noor Gulf Trading", "Unrelated Co"])
def test_engine_never_over_allocates_or_crosses_currency(amount, allocated, currency, sender):
    invoice = inv(total="10000.00", allocated=allocated)
    d = decide(pay(amount=amount, currency=currency, sender=sender), invoice)

    # 1. never more than the payment, never more than the invoice's outstanding balance
    assert d.allocate <= D(amount)
    assert d.allocate <= max(invoice.outstanding, D("0"))
    # 2. money moves only on MATCHED / PARTIAL, and then it moves the whole payment
    if d.allocate > 0:
        assert d.status in (S.MATCHED, S.PARTIAL)
        assert d.allocate == D(amount)
        # 3. only with a matching currency and a convincing buyer name
        assert currency == "USD" and sender == "Acme Imports LLC"
    else:
        assert d.status not in (S.MATCHED, S.PARTIAL)
    # 4. every decision carries an explanation
    assert d.explanation


def test_decisions_are_deterministic():
    args = (pay(sender="Noor Gulf Trading"), inv(buyer="Al Noor General Trading LLC"))
    assert decide(*args) == decide(*args)


def test_engine_does_not_mutate_its_inputs():
    invoice = inv()
    payment = pay()
    before = (invoice, payment)
    decide(payment, invoice)
    assert (invoice, payment) == before
