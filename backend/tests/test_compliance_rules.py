import pytest

from app.models.enums import DocumentStatus as S
from app.models.enums import DocumentType as T
from app.services.compliance_rules import (
    ALWAYS_REQUIRED,
    CHECKLIST,
    ChecklistConfig,
    DocState,
    ManualCheck,
    assess_readiness,
    build_item,
    document_status,
    effective_status,
    is_required,
    summarise,
)

PACKING = next(c for c in CHECKLIST if c.document_type == T.PACKING_LIST)
REMITTANCE = next(c for c in CHECKLIST if c.document_type == T.REMITTANCE_ADVICE)


def doc(status: S, name="a.pdf") -> DocState:
    return DocState(id=name, file_name=name, verification_status=status)


def manual(status: S, remarks="seen paper copy") -> ManualCheck:
    return ManualCheck(status=status, remarks=remarks, reviewed_by="Olivia", reviewed_at=None)


# ------------------------------------------------------------------ the checklist configuration


def test_checklist_covers_the_documents_named_in_the_brd():
    assert [c.document_type for c in CHECKLIST] == [
        T.COMMERCIAL_INVOICE, T.PACKING_LIST, T.SHIPPING_BILL, T.BILL_OF_LADING, T.REMITTANCE_ADVICE,
    ]
    assert T.REMITTANCE_ADVICE not in ALWAYS_REQUIRED and len(ALWAYS_REQUIRED) == 4


def test_remittance_advice_is_only_required_once_money_has_arrived():
    assert is_required(REMITTANCE, invoice_has_payments=False) is False
    assert is_required(REMITTANCE, invoice_has_payments=True) is True
    assert is_required(PACKING, invoice_has_payments=False) is True


# ------------------------------------------------------------------ status from documents


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], S.NOT_UPLOADED),
        ([S.UPLOADED], S.UPLOADED),
        ([S.UNDER_REVIEW], S.UNDER_REVIEW),
        ([S.VERIFIED], S.VERIFIED),
        ([S.REJECTED], S.REJECTED),
        ([S.REJECTED, S.UPLOADED], S.UPLOADED),  # a re-upload after a rejection moves the item forward
        ([S.REJECTED, S.VERIFIED], S.VERIFIED),
        ([S.UPLOADED, S.UNDER_REVIEW], S.UNDER_REVIEW),
        ([S.UNDER_REVIEW, S.VERIFIED, S.REJECTED], S.VERIFIED),
    ],
)
def test_the_most_advanced_document_represents_the_item(statuses, expected):
    assert document_status([doc(s, f"{i}.pdf") for i, s in enumerate(statuses)]) == expected


# ------------------------------------------------------------------ manual review vs documents


def test_a_verified_document_always_counts_even_over_a_manual_rejection():
    assert effective_status([doc(S.VERIFIED)], manual(S.REJECTED)) == (S.VERIFIED, "DOCUMENT")


@pytest.mark.parametrize("doc_status", [S.UPLOADED, S.UNDER_REVIEW, S.REJECTED])
def test_a_manual_review_decides_when_no_document_is_verified(doc_status):
    assert effective_status([doc(doc_status)], manual(S.VERIFIED)) == (S.VERIFIED, "MANUAL")
    assert effective_status([doc(doc_status)], manual(S.REJECTED)) == (S.REJECTED, "MANUAL")


def test_a_manual_review_works_without_any_uploaded_document():
    assert effective_status([], manual(S.VERIFIED)) == (S.VERIFIED, "MANUAL")


def test_without_documents_or_reviews_the_item_is_not_uploaded():
    assert effective_status([], None) == (S.NOT_UPLOADED, "NONE")
    assert effective_status([doc(S.UPLOADED)], None) == (S.UPLOADED, "DOCUMENT")


# ------------------------------------------------------------------ summary


def items(**statuses):
    out = []
    for config in CHECKLIST:
        status = statuses.get(config.document_type.value, S.NOT_UPLOADED)
        docs = [] if status == S.NOT_UPLOADED else [doc(status, f"{config.document_type.value}.pdf")]
        out.append(build_item(config, docs, None, invoice_has_payments=statuses.get("paid", False)))
    return out


def test_summary_of_an_empty_invoice():
    s = summarise(items())
    assert (s.required_total, s.verified, s.missing, s.flagged, s.complete) == (4, 0, 4, 0, False)


def test_summary_counts_each_state_among_required_items_only():
    s = summarise(items(COMMERCIAL_INVOICE=S.VERIFIED, PACKING_LIST=S.UNDER_REVIEW, SHIPPING_BILL=S.UPLOADED, BILL_OF_LADING=S.REJECTED, REMITTANCE_ADVICE=S.VERIFIED))
    assert (s.required_total, s.verified, s.under_review, s.uploaded, s.rejected, s.missing) == (4, 1, 1, 1, 1, 1)  # remittance not counted yet


def test_remittance_counts_once_there_are_payments():
    all_verified = {c.document_type.value: S.VERIFIED for c in CHECKLIST}
    assert summarise(items(**all_verified, paid=False)).required_total == 4
    after_payment = summarise(items(**{**all_verified, "REMITTANCE_ADVICE": S.NOT_UPLOADED}, paid=True))
    assert after_payment.required_total == 5 and after_payment.complete is False and after_payment.missing == 1


def test_complete_requires_everything_verified_and_nothing_flagged():
    everything = {c.document_type.value: S.VERIFIED for c in CHECKLIST if c.requirement == "ALWAYS"}
    assert summarise(items(**everything)).complete is True
    flagged = [build_item(c, [doc(S.VERIFIED)], None, False, has_mismatch=(c.document_type == T.PACKING_LIST)) for c in CHECKLIST]
    result = summarise(flagged)
    assert result.verified == 4 and result.flagged == 1 and result.complete is False


def test_an_invoice_with_no_required_items_is_never_complete():
    assert summarise([]).complete is False
    assert summarise([build_item(REMITTANCE, [doc(S.VERIFIED)], None, invoice_has_payments=False)]).complete is False


# ------------------------------------------------------------------ readiness (simulated export-filing readiness)


def test_ready_only_when_paid_verified_and_consistent():
    verified = [build_item(c, [doc(S.VERIFIED)], None, True) for c in CHECKLIST]
    r = assess_readiness("PAID", verified)
    assert r.ready is True and r.reasons == []


def test_not_ready_lists_every_reason():
    partly = [build_item(c, [doc(S.VERIFIED)] if c.document_type == T.COMMERCIAL_INVOICE else [], None, True, has_mismatch=c.document_type == T.COMMERCIAL_INVOICE) for c in CHECKLIST]
    r = assess_readiness("PARTIALLY_PAID", partly)
    assert r.ready is False
    assert any("not paid in full" in x for x in r.reasons)
    assert any("Packing List" in x and "Remittance Advice" in x for x in r.reasons)
    assert any("Differences from the invoice" in x and "Commercial Invoice" in x for x in r.reasons)


def test_paid_but_missing_documents_is_not_ready():
    r = assess_readiness("PAID", [build_item(c, [], None, True) for c in CHECKLIST])
    assert r.ready is False and len(r.reasons) == 1 and "Documents not verified" in r.reasons[0]


def test_documents_complete_but_unpaid_is_not_ready():
    r = assess_readiness("OVERDUE", [build_item(c, [doc(S.VERIFIED)], None, False) for c in CHECKLIST if c.requirement == "ALWAYS"])
    assert r.ready is False and r.reasons == ["The invoice is not paid in full yet"]


def test_custom_configuration_flows_through():
    only_one = ChecklistConfig(T.OTHER, "Insurance certificate", "ALWAYS")
    item = build_item(only_one, [doc(S.VERIFIED)], None, False)
    assert summarise([item]).complete is True and item.required is True
