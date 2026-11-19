import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.db.seed import seed_demo_data
from app.main import app
from app.models.audit import AuditLog
from app.models.document import ComplianceCheck, Document
from app.models.enums import DocumentStatus, DocumentType, ExtractionStatus
from app.models.invoice import Invoice
from app.services.ollama_service import get_llm
from tests.fakes import FakeLLM

URL = "/api/v1/compliance"
S, T = DocumentStatus, DocumentType


@pytest.fixture
def reconciled(client, finance, db):
    seed_demo_data(db)
    db.commit()
    assert client.post("/api/v1/reconciliation/run", headers=finance).status_code == 200


def invoice(db, number: str) -> Invoice:
    return db.scalar(select(Invoice).where(Invoice.invoice_number == number))


def matching_fields(inv: Invoice, **overrides) -> dict:
    """What a perfect extraction of this invoice's own commercial invoice would contain."""
    fields = {
        "document_type": "COMMERCIAL_INVOICE", "invoice_number": inv.invoice_number,
        "exporter_name": inv.exporter.company_name, "buyer_name": inv.buyer.buyer_name, "buyer_country": inv.buyer.country,
        "currency": inv.currency, "invoice_amount": f"{inv.total_amount:.2f}",
        "invoice_date": inv.invoice_date.isoformat(), "due_date": inv.due_date.isoformat(),
    }
    return {**fields, **overrides}


def add_doc(db, inv: Invoice, doc_type=T.COMMERCIAL_INVOICE, status=S.UPLOADED, fields: dict | None = None, confirmed: dict | None = None, name=None):
    extracted = {"fields": fields, "quality": {}, "llm_confidence": {}, "issues": [], "model": "m", "truncated": False, "page_count": 1} if fields else None
    doc = Document(
        invoice_id=inv.id, file_name=name or f"{doc_type.value.lower()}.pdf", file_path="x.pdf", document_type=doc_type,
        extraction_status=ExtractionStatus.COMPLETED if fields else ExtractionStatus.NOT_STARTED, verification_status=status,
        extracted_data=extracted, confirmed_data={"fields": confirmed, "decision": "VERIFIED"} if confirmed else None,
    )
    db.add(doc)
    db.commit()
    return doc


def verify_all(db, inv: Invoice, include_remittance=True):
    for t in (T.COMMERCIAL_INVOICE, T.PACKING_LIST, T.SHIPPING_BILL, T.BILL_OF_LADING, *([T.REMITTANCE_ADVICE] if include_remittance else [])):
        add_doc(db, inv, t, S.VERIFIED, fields=matching_fields(inv) if t == T.COMMERCIAL_INVOICE else None)


def get(client, headers, invoice_id):
    return client.get(f"{URL}/{invoice_id}", headers=headers)


def item(body, doc_type):
    return next(i for i in body["items"] if i["document_type"] == doc_type)


# ======================================================================== the checklist


def test_a_new_invoice_has_an_empty_checklist(client, ops, reconciled, db):
    body = get(client, ops, invoice(db, "INV-1021").id).json()  # no payments yet
    assert [i["document_type"] for i in body["items"]] == ["COMMERCIAL_INVOICE", "PACKING_LIST", "SHIPPING_BILL", "BILL_OF_LADING", "REMITTANCE_ADVICE"]
    assert {i["status"] for i in body["items"]} == {"NOT_UPLOADED"}
    assert body["summary"] == {"required_total": 4, "verified": 0, "under_review": 0, "uploaded": 0, "rejected": 0, "missing": 4, "flagged": 0, "complete": False}
    remittance = item(body, "REMITTANCE_ADVICE")
    assert remittance["required"] is False and "once a payment" in remittance["requirement_note"]
    assert "not legal or regulatory approval" in body["disclaimer"]


def test_remittance_advice_becomes_required_after_a_payment(client, ops, reconciled, db):
    body = get(client, ops, invoice(db, "INV-1010").id).json()  # paid in full
    assert item(body, "REMITTANCE_ADVICE")["required"] is True and body["summary"]["required_total"] == 5


@pytest.mark.parametrize("status", [S.UPLOADED, S.UNDER_REVIEW, S.VERIFIED, S.REJECTED])
def test_item_status_follows_the_uploaded_document(client, ops, reconciled, db, status):
    inv = invoice(db, "INV-1021")
    add_doc(db, inv, T.PACKING_LIST, status, name="packing.pdf")
    packing = item(get(client, ops, inv.id).json(), "PACKING_LIST")
    assert packing["status"] == status.value and packing["source"] == "DOCUMENT"
    assert packing["documents"][0]["file_name"] == "packing.pdf"


def test_the_most_advanced_document_wins_and_a_reupload_after_rejection_moves_forward(client, ops, reconciled, db):
    inv = invoice(db, "INV-1021")
    add_doc(db, inv, T.SHIPPING_BILL, S.REJECTED, name="bad.pdf")
    assert item(get(client, ops, inv.id).json(), "SHIPPING_BILL")["status"] == "REJECTED"
    add_doc(db, inv, T.SHIPPING_BILL, S.UPLOADED, name="good.pdf")
    body = item(get(client, ops, inv.id).json(), "SHIPPING_BILL")
    assert body["status"] == "UPLOADED" and len(body["documents"]) == 2


def test_unknown_invoice_is_404(client, ops):
    assert get(client, ops, uuid.uuid4()).status_code == 404
    assert client.get(f"{URL}/not-a-uuid", headers=ops).status_code == 422


# ======================================================================== manual review


def check(client, headers, inv, doc_type="SHIPPING_BILL", status="VERIFIED", remarks=None):
    return client.post(f"{URL}/{inv.id}/checks", json={"document_type": doc_type, "status": status, "remarks": remarks}, headers=headers)


def test_a_manual_review_is_recorded_with_who_and_why(client, ops, reconciled, db):
    inv = invoice(db, "INV-1021")
    resp = check(client, ops, inv, remarks="Original paper copy inspected at the port office")
    assert resp.status_code == 200
    ship = item(resp.json(), "SHIPPING_BILL")
    assert ship["status"] == "VERIFIED" and ship["source"] == "MANUAL"
    assert ship["reviewed_by"] == "Olivia Operations" and "paper copy" in ship["remarks"] and ship["reviewed_at"]
    assert resp.json()["summary"]["verified"] == 1


def test_verifying_with_nothing_uploaded_requires_an_explanation(client, ops, reconciled, db):
    inv = invoice(db, "INV-1021")
    for remarks in (None, "", "  ", "ok"):
        resp = check(client, ops, inv, remarks=remarks)
        assert resp.status_code == 422 and "how it was verified" in resp.json()["detail"]
    assert db.scalar(select(ComplianceCheck)) is None  # nothing was recorded


def test_verifying_an_uploaded_document_needs_no_extra_remarks(client, ops, reconciled, db):
    inv = invoice(db, "INV-1021")
    add_doc(db, inv, T.PACKING_LIST, S.UPLOADED)
    assert check(client, ops, inv, "PACKING_LIST", "VERIFIED").status_code == 200


def test_reviews_are_append_only_and_the_latest_one_decides(client, ops, reconciled, db):
    inv = invoice(db, "INV-1021")
    check(client, ops, inv, status="UNDER_REVIEW")
    check(client, ops, inv, status="REJECTED", remarks="Illegible scan")
    last = item(check(client, ops, inv, status="VERIFIED", remarks="Re-checked the paper original").json(), "SHIPPING_BILL")
    assert last["status"] == "VERIFIED" and last["remarks"] == "Re-checked the paper original"
    assert len(db.scalars(select(ComplianceCheck)).all()) == 3  # the history is kept
    logs = db.scalars(select(AuditLog).where(AuditLog.action == "COMPLIANCE_CHECK_RECORDED").order_by(AuditLog.created_at)).all()
    assert len(logs) == 3 and logs[1].old_values["status"] == "UNDER_REVIEW" and logs[1].new_values["status"] == "REJECTED"


def test_a_verified_document_always_counts_even_after_a_manual_rejection(client, ops, reconciled, db):
    inv = invoice(db, "INV-1021")
    add_doc(db, inv, T.PACKING_LIST, S.VERIFIED)
    resp = check(client, ops, inv, "PACKING_LIST", "REJECTED", remarks="Looked wrong on first glance")
    packing = item(resp.json(), "PACKING_LIST")
    assert packing["status"] == "VERIFIED" and packing["source"] == "DOCUMENT"


def test_a_manual_rejection_overrides_an_unverified_document(client, ops, reconciled, db):
    inv = invoice(db, "INV-1021")
    add_doc(db, inv, T.PACKING_LIST, S.UNDER_REVIEW)
    assert item(check(client, ops, inv, "PACKING_LIST", "REJECTED", remarks="Wrong consignment").json(), "PACKING_LIST")["status"] == "REJECTED"


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"document_type": "OTHER", "status": "VERIFIED", "remarks": "fine fine"}, 422),
        ({"document_type": "PACKING_LIST", "status": "NOT_UPLOADED"}, 422),
        ({"document_type": "PACKING_LIST", "status": "UPLOADED"}, 422),
        ({"document_type": "NOPE", "status": "VERIFIED"}, 422),
        ({"status": "VERIFIED"}, 422),
        ({"document_type": "PACKING_LIST", "status": "REJECTED", "remarks": "x" * 501}, 422),
    ],
)
def test_invalid_reviews_are_rejected(client, ops, reconciled, db, payload, status):
    assert client.post(f"{URL}/{invoice(db, 'INV-1021').id}/checks", json=payload, headers=ops).status_code == status


def test_drafts_and_unknown_invoices_cannot_be_reviewed(client, ops, reconciled, db):
    assert check(client, ops, invoice(db, "INV-1023"), remarks="some remarks").status_code == 409  # a draft
    ghost = client.post(f"{URL}/{uuid.uuid4()}/checks", json={"document_type": "PACKING_LIST", "status": "REJECTED"}, headers=ops)
    assert ghost.status_code == 404


# ======================================================================== consistency with the invoice


def test_a_document_that_agrees_with_the_invoice_has_no_flags(client, ops, reconciled, db):
    inv = invoice(db, "INV-1021")
    add_doc(db, inv, T.COMMERCIAL_INVOICE, S.UNDER_REVIEW, fields=matching_fields(inv), name="inv.pdf")
    ci = item(get(client, ops, inv.id).json(), "COMMERCIAL_INVOICE")
    assert ci["has_mismatch"] is False and ci["compared_document"] == "inv.pdf"
    assert {f["status"] for f in ci["findings"]} == {"MATCH"} and len(ci["findings"]) == 7


def test_a_difference_flags_the_item_and_the_invoice(client, ops, reconciled, db):
    inv = invoice(db, "INV-1021")
    add_doc(db, inv, T.COMMERCIAL_INVOICE, S.VERIFIED, fields=matching_fields(inv, invoice_amount="5700.00", currency="EUR"))
    body = get(client, ops, inv.id).json()
    ci = item(body, "COMMERCIAL_INVOICE")
    assert ci["has_mismatch"] is True
    assert {f["field"] for f in ci["findings"] if f["status"] == "MISMATCH"} == {"invoice_amount", "currency"}
    assert body["summary"]["flagged"] == 1
    assert ci["status"] == "VERIFIED"  # verified, yet still flagged: a person should look at the difference


def test_confirmed_values_win_over_the_ai_draft(client, ops, reconciled, db):
    inv = invoice(db, "INV-1021")
    wrong_draft = matching_fields(inv, invoice_amount="1.00")
    add_doc(db, inv, T.COMMERCIAL_INVOICE, S.VERIFIED, fields=wrong_draft, confirmed=matching_fields(inv))
    assert item(get(client, ops, inv.id).json(), "COMMERCIAL_INVOICE")["has_mismatch"] is False  # the person corrected it


def test_a_rejected_document_is_not_compared(client, ops, reconciled, db):
    inv = invoice(db, "INV-1021")
    add_doc(db, inv, T.COMMERCIAL_INVOICE, S.REJECTED, fields=matching_fields(inv, invoice_amount="1.00"))
    ci = item(get(client, ops, inv.id).json(), "COMMERCIAL_INVOICE")
    assert ci["has_mismatch"] is False and ci["findings"] == [] and ci["compared_document"] is None


def test_missing_values_are_not_treated_as_differences(client, ops, reconciled, db):
    inv = invoice(db, "INV-1021")
    add_doc(db, inv, T.COMMERCIAL_INVOICE, S.UNDER_REVIEW, fields={"invoice_number": inv.invoice_number})
    ci = item(get(client, ops, inv.id).json(), "COMMERCIAL_INVOICE")
    assert ci["has_mismatch"] is False
    assert {f["status"] for f in ci["findings"]} == {"MATCH", "NOT_COMPARABLE"}


def test_the_latest_document_of_a_type_is_the_one_compared(client, ops, reconciled, db):
    inv = invoice(db, "INV-1021")
    add_doc(db, inv, T.COMMERCIAL_INVOICE, S.UNDER_REVIEW, fields=matching_fields(inv, invoice_amount="1.00"), name="old.pdf")
    add_doc(db, inv, T.COMMERCIAL_INVOICE, S.UNDER_REVIEW, fields=matching_fields(inv), name="new.pdf")
    ci = item(get(client, ops, inv.id).json(), "COMMERCIAL_INVOICE")
    assert ci["compared_document"] == "new.pdf" and ci["has_mismatch"] is False


# ======================================================================== readiness (simulated)


def test_an_invoice_is_ready_only_when_paid_verified_and_consistent(client, ops, reconciled, db):
    inv = invoice(db, "INV-1010")  # paid in full
    verify_all(db, inv)
    body = get(client, ops, inv.id).json()
    assert body["summary"]["complete"] is True and body["readiness"] == {"ready": True, "reasons": []}


def test_not_ready_explains_why(client, ops, reconciled, db):
    unpaid = get(client, ops, invoice(db, "INV-1013").id).json()  # overdue and unpaid
    reasons = " | ".join(unpaid["readiness"]["reasons"])
    assert unpaid["readiness"]["ready"] is False and "not paid in full" in reasons and "Documents not verified" in reasons


def test_paid_and_verified_but_inconsistent_is_not_ready(client, ops, reconciled, db):
    inv = invoice(db, "INV-1010")
    verify_all(db, inv)
    add_doc(db, inv, T.COMMERCIAL_INVOICE, S.VERIFIED, fields=matching_fields(inv, invoice_amount="999.00"), name="newer.pdf")
    body = get(client, ops, inv.id).json()
    assert body["readiness"]["ready"] is False and any("Differences from the invoice" in r for r in body["readiness"]["reasons"])


# ======================================================================== overview


def test_overview_lists_issued_invoices_incomplete_first(client, ops, reconciled, db):
    complete = invoice(db, "INV-1010")
    verify_all(db, complete)
    page = client.get(URL, params={"page_size": 100}, headers=ops).json()
    assert page["total"] == 14  # the draft is not tracked
    numbers = [r["invoice_number"] for r in page["items"]]
    assert "INV-1023" not in numbers and numbers[-1] == "INV-1010"  # the only complete one sorts last
    done = page["items"][-1]
    assert (done["complete"], done["ready"], done["verified"], done["required_total"], done["missing"]) == (True, True, 5, 5, 0)
    first = page["items"][0]
    assert first["complete"] is False and first["missing"] == first["required_total"]


def test_overview_filters_and_paging(client, ops, reconciled, db):
    verify_all(db, invoice(db, "INV-1010"))
    assert client.get(URL, params={"incomplete_only": True, "page_size": 100}, headers=ops).json()["total"] == 13
    assert [r["invoice_number"] for r in client.get(URL, params={"search": "inv-1024"}, headers=ops).json()["items"]] == ["INV-1024"]
    assert client.get(URL, params={"search": "harbor"}, headers=ops).json()["total"] == 2
    paged = client.get(URL, params={"page": 2, "page_size": 5}, headers=ops).json()
    assert paged["total"] == 14 and paged["pages"] == 3 and len(paged["items"]) == 5
    assert client.get(URL, params={"page_size": 500}, headers=ops).status_code == 422


def test_overview_reflects_flags(client, ops, reconciled, db):
    inv = invoice(db, "INV-1021")
    add_doc(db, inv, T.COMMERCIAL_INVOICE, S.VERIFIED, fields=matching_fields(inv, invoice_amount="1.00"))
    row = next(r for r in client.get(URL, params={"search": "INV-1021"}, headers=ops).json()["items"])
    assert row["flagged"] == 1 and row["verified"] == 1 and row["complete"] is False


# ======================================================================== authorization


def test_compliance_endpoints_are_for_operations_and_admin(client, finance, ops, admin, reconciled, db):
    inv = invoice(db, "INV-1021")
    assert client.get(URL).status_code == 401
    for headers, expected in ((finance, 403), (ops, 200), (admin, 200)):
        assert client.get(URL, headers=headers).status_code == expected
        assert get(client, headers, inv.id).status_code == expected
    assert check(client, finance, inv, remarks="some remarks").status_code == 403
    assert check(client, admin, inv, remarks="admin inspected it").status_code == 200


# ======================================================================== lifecycle timeline (every role)


def lifecycle(client, headers, inv):
    return client.get(f"/api/v1/invoices/{inv.id}/lifecycle", headers=headers)


def steps(body):
    return {s["key"]: s for s in body["steps"]}


def test_lifecycle_of_a_partly_paid_invoice(client, finance, reconciled, db):
    s = steps(lifecycle(client, finance, invoice(db, "INV-1024")).json())
    assert [k for k in s] == ["INVOICED", "PAYMENT_RECEIVED", "PAID_IN_FULL", "DOCUMENTS_VERIFIED", "FILING_READINESS"]
    assert s["INVOICED"]["state"] == "DONE" and s["INVOICED"]["date"]
    assert s["PAYMENT_RECEIVED"]["state"] == "DONE" and "USD 9,500.00 of USD 10,000.00" in s["PAYMENT_RECEIVED"]["detail"]
    assert s["PAID_IN_FULL"]["state"] == "IN_PROGRESS" and "USD 500.00 still outstanding" in s["PAID_IN_FULL"]["detail"]
    assert s["DOCUMENTS_VERIFIED"]["state"] == "PENDING" and s["FILING_READINESS"]["state"] == "PENDING"


def test_lifecycle_of_a_paid_invoice_with_all_documents_is_ready(client, ops, reconciled, db):
    inv = invoice(db, "INV-1010")
    before = steps(lifecycle(client, ops, inv).json())
    assert before["PAID_IN_FULL"]["state"] == "DONE" and before["PAID_IN_FULL"]["date"]
    assert before["DOCUMENTS_VERIFIED"]["state"] == "PENDING" and before["FILING_READINESS"]["state"] == "PENDING"
    verify_all(db, inv)
    body = lifecycle(client, ops, inv).json()
    after = steps(body)
    assert after["DOCUMENTS_VERIFIED"]["state"] == "DONE" and "5 of 5" in after["DOCUMENTS_VERIFIED"]["detail"]
    assert after["FILING_READINESS"]["state"] == "DONE" and body["readiness"]["ready"] is True
    assert "does not file" in body["note"]


def test_documents_in_progress_show_progress(client, ops, reconciled, db):
    inv = invoice(db, "INV-1021")
    add_doc(db, inv, T.PACKING_LIST, S.VERIFIED)
    s = steps(lifecycle(client, ops, inv).json())
    assert s["DOCUMENTS_VERIFIED"]["state"] == "IN_PROGRESS" and "1 of 4" in s["DOCUMENTS_VERIFIED"]["detail"]


def test_lifecycle_of_a_draft_and_a_cancelled_invoice(client, finance, reconciled, db):
    draft = steps(lifecycle(client, finance, invoice(db, "INV-1023")).json())
    assert draft["INVOICED"]["state"] == "PENDING" and "draft" in draft["INVOICED"]["detail"].lower()
    cancelled = invoice(db, "INV-1021")
    cancelled.status = InvoiceStatus_CANCELLED()
    db.commit()
    body = lifecycle(client, finance, cancelled).json()
    assert {s["state"] for s in body["steps"]} == {"NOT_APPLICABLE"} and body["readiness"]["ready"] is False


def InvoiceStatus_CANCELLED():  # noqa: N802
    from app.models.enums import InvoiceStatus

    return InvoiceStatus.CANCELLED


def test_lifecycle_is_readable_by_every_role_but_needs_a_login(client, finance, ops, admin, reconciled, db):
    inv = invoice(db, "INV-1024")
    assert client.get(f"/api/v1/invoices/{inv.id}/lifecycle").status_code == 401
    assert all(lifecycle(client, h, inv).status_code == 200 for h in (finance, ops, admin))
    assert client.get(f"/api/v1/invoices/{uuid.uuid4()}/lifecycle", headers=ops).status_code == 404


def test_lifecycle_shows_only_progress_never_document_contents(client, finance, reconciled, db):
    inv = invoice(db, "INV-1021")
    add_doc(db, inv, T.COMMERCIAL_INVOICE, S.VERIFIED, fields=matching_fields(inv), name="secret-name.pdf")
    blob = lifecycle(client, finance, inv).text
    assert "secret-name" not in blob and inv.buyer.buyer_name in blob  # counts and the buyer, no file or field contents


# ======================================================================== consistency with the Copilot


def test_the_copilot_agrees_with_the_checklist_about_what_is_missing(client, ops, reconciled, db):
    app.dependency_overrides[get_llm] = lambda: FakeLLM(down=True)
    try:
        inv = invoice(db, "INV-1021")
        question = {"message": "Show invoices with missing supporting documents."}
        before = client.post("/api/v1/ai/chat", json=question, headers=ops).json()
        assert any(r["invoice"] == "INV-1021" for r in before["table"]["rows"])
        for t in ("COMMERCIAL_INVOICE", "PACKING_LIST", "SHIPPING_BILL", "BILL_OF_LADING"):
            check(client, ops, inv, t, "VERIFIED", remarks="Paper originals inspected")
        after = client.post("/api/v1/ai/chat", json=question, headers=ops).json()
        assert all(r["invoice"] != "INV-1021" for r in after["table"]["rows"])
        assert "13 issued invoices" in after["answer"]
    finally:
        app.dependency_overrides.pop(get_llm, None)
