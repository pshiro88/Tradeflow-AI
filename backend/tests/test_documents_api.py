import uuid
from datetime import date
from decimal import Decimal

import pymupdf
import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.errors import AIResponseError
from app.main import app
from app.models.audit import AIAuditLog, AuditLog
from app.models.document import Document
from app.models.enums import DocumentStatus, ExtractionStatus
from app.models.invoice import Invoice
from app.models.party import Buyer, Exporter
from app.models.payment import Payment
from app.services.ollama_service import get_llm
from tests.fakes import GOOD_EXTRACTION, INVOICE_TEXT, FakeLLM, make_pdf, rewrite_draft

URL = "/api/v1/documents"


@pytest.fixture(autouse=True)
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))
    return tmp_path / "uploads"


@pytest.fixture
def use_llm():
    """Install a scripted LLM for the duration of a test."""

    def install(llm: FakeLLM) -> FakeLLM:
        app.dependency_overrides[get_llm] = lambda: llm
        return llm

    yield install
    app.dependency_overrides.pop(get_llm, None)


@pytest.fixture
def invoice(db) -> Invoice:
    exporter = Exporter(company_name="Meridian Engineering Works Pvt Ltd", country="India")
    buyer = Buyer(buyer_name="Harbor & Pine Trading Co", country="USA")
    db.add_all([exporter, buyer])
    db.flush()
    inv = Invoice(
        invoice_number="INV-1024", exporter_id=exporter.id, buyer_id=buyer.id, invoice_date=date(2026, 11, 10),
        due_date=date(2026, 12, 25), currency="USD", total_amount=Decimal("10000.00"),
    )
    db.add(inv)
    db.commit()
    return inv


def upload(client, headers, content=None, name="invoice.pdf", doc_type="COMMERCIAL_INVOICE", invoice_id=None):
    data = {"document_type": doc_type}
    if invoice_id:
        data["invoice_id"] = str(invoice_id)
    return client.post(
        f"{URL}/upload", data=data, headers=headers,
        files={"file": (name, make_pdf(INVOICE_TEXT) if content is None else content, "application/pdf")},
    )


def uploaded_id(client, ops, **kwargs) -> str:
    resp = upload(client, ops, **kwargs)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def stored_files(upload_dir):
    return sorted(p.name for p in upload_dir.glob("*")) if upload_dir.exists() else []


# ======================================================================== upload


def test_upload_registers_and_stores_a_pdf(client, ops, upload_dir, invoice):
    resp = upload(client, ops, invoice_id=invoice.id)
    assert resp.status_code == 201
    body = resp.json()
    assert body["file_name"] == "invoice.pdf" and body["document_type"] == "COMMERCIAL_INVOICE"
    assert body["extraction_status"] == "NOT_STARTED" and body["verification_status"] == "UPLOADED"
    assert body["invoice_number"] == "INV-1024" and body["uploaded_by_name"] == "Olivia Operations"
    assert body["extraction"] is None and body["confirmation"] is None
    files = stored_files(upload_dir)
    assert len(files) == 1 and files[0].endswith(".pdf") and files[0] != "invoice.pdf"  # stored under a generated name


def test_uploaded_file_name_is_sanitised(client, ops, upload_dir):
    body = upload(client, ops, name="../../etc/evil.pdf").json()
    assert body["file_name"] == "evil.pdf"
    assert all(".." not in f and "/" not in f for f in stored_files(upload_dir))
    assert upload(client, ops, name="C:\\Windows\\x\\bad.pdf").json()["file_name"] == "bad.pdf"


def test_upload_is_audited(client, ops, db):
    upload(client, ops)
    assert db.scalar(select(AuditLog).where(AuditLog.action == "DOCUMENT_UPLOADED")) is not None


@pytest.mark.parametrize(
    ("kwargs", "status", "message"),
    [
        ({"name": "invoice.docx"}, 422, ".pdf"),
        ({"content": b"not a pdf, just text"}, 422, "not a PDF"),
        ({"content": b"%PDF-1.7 corrupted garbage"}, 422, "corrupted"),
        ({"content": b""}, 422, "empty"),
        ({"doc_type": "LOVE_LETTER"}, 422, None),
    ],
)
def test_invalid_uploads_are_rejected_and_leave_nothing_behind(client, ops, db, upload_dir, kwargs, status, message):
    resp = upload(client, ops, **kwargs)
    assert resp.status_code == status
    if message:
        assert message in str(resp.json()["detail"])
    assert stored_files(upload_dir) == []
    assert db.scalar(select(func.count()).select_from(Document)) == 0


def test_scanned_pdf_without_text_is_rejected(client, ops):
    doc = pymupdf.open()
    doc.new_page()
    resp = upload(client, ops, content=doc.tobytes())
    assert resp.status_code == 422 and "Scanned or image-only" in resp.json()["detail"]


def test_oversized_upload_returns_413(client, ops, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    assert upload(client, ops).status_code == 413


def test_upload_to_unknown_invoice_is_rejected(client, ops, upload_dir):
    resp = upload(client, ops, invoice_id=uuid.uuid4())
    assert resp.status_code == 422 and stored_files(upload_dir) == []


def test_upload_requires_a_file(client, ops):
    assert client.post(f"{URL}/upload", data={"document_type": "OTHER"}, headers=ops).status_code == 422


# ======================================================================== authorization


def test_unauthenticated_requests_return_401(client):
    assert client.get(URL).status_code == 401
    assert client.post(f"{URL}/upload", data={"document_type": "OTHER"}).status_code == 401


def test_finance_cannot_use_documents(client, finance, ops):
    doc_id = uploaded_id(client, ops)
    assert client.get(URL, headers=finance).status_code == 403
    assert client.get(f"{URL}/{doc_id}", headers=finance).status_code == 403
    assert client.post(f"{URL}/{doc_id}/extract", headers=finance).status_code == 403
    assert client.post(f"{URL}/{doc_id}/verify", json={"decision": "REJECTED"}, headers=finance).status_code == 403
    assert upload(client, finance).status_code == 403


def test_admin_can_use_documents(client, admin, use_llm):
    use_llm(FakeLLM(json_response=GOOD_EXTRACTION))
    doc_id = uploaded_id(client, admin)
    assert client.post(f"{URL}/{doc_id}/extract", headers=admin).status_code == 200


# ======================================================================== extraction


def test_extraction_produces_a_validated_draft_for_review(client, ops, use_llm, db):
    use_llm(FakeLLM(json_response=GOOD_EXTRACTION))
    doc_id = uploaded_id(client, ops)
    resp = client.post(f"{URL}/{doc_id}/extract", headers=ops)
    assert resp.status_code == 200
    body = resp.json()
    assert body["extraction_status"] == "COMPLETED" and body["verification_status"] == "UNDER_REVIEW"
    extraction = body["extraction"]
    assert extraction["fields"]["invoice_amount"] == "10000.00"  # a string, never a float
    assert extraction["fields"]["invoice_date"] == "2026-11-10"
    assert extraction["quality"]["invoice_number"] == "FOUND_IN_TEXT"
    assert extraction["quality"]["document_type"] == "INFERRED"
    assert extraction["llm_confidence"]["invoice_number"] == 0.98
    assert extraction["model"] == "fake-model" and extraction["truncated"] is False and extraction["page_count"] == 1
    assert body["confirmation"] is None  # nothing is confirmed until a person does it


def test_extraction_never_creates_financial_records(client, ops, use_llm, db):
    use_llm(FakeLLM(json_response=GOOD_EXTRACTION))
    client.post(f"{URL}/{uploaded_id(client, ops)}/extract", headers=ops)
    assert db.scalar(select(func.count()).select_from(Invoice)) == 0
    assert db.scalar(select(func.count()).select_from(Payment)) == 0


def test_hallucinated_values_are_flagged_not_trusted(client, ops, use_llm):
    use_llm(FakeLLM(json_response={**GOOD_EXTRACTION, "invoice_amount": "77777.00", "buyer_name": "Imaginary Corp"}))
    extraction = client.post(f"{URL}/{uploaded_id(client, ops)}/extract", headers=ops).json()["extraction"]
    assert extraction["quality"]["invoice_amount"] == "NOT_FOUND_IN_TEXT"
    assert extraction["quality"]["buyer_name"] == "NOT_FOUND_IN_TEXT"
    assert extraction["quality"]["invoice_number"] == "FOUND_IN_TEXT"


def test_invalid_model_values_become_null_with_a_visible_issue(client, ops, use_llm):
    use_llm(FakeLLM(json_response={**GOOD_EXTRACTION, "invoice_amount": "lots", "due_date": "10/12/2026"}))
    extraction = client.post(f"{URL}/{uploaded_id(client, ops)}/extract", headers=ops).json()["extraction"]
    assert extraction["fields"]["invoice_amount"] is None and extraction["fields"]["due_date"] is None
    assert {i["field"] for i in extraction["issues"]} == {"invoice_amount", "due_date"}
    assert extraction["quality"]["invoice_amount"] == "MISSING"


def test_unknown_fields_stay_null_instead_of_being_invented(client, ops, use_llm):
    use_llm(FakeLLM(json_response={"invoice_number": "INV-1024"}))
    fields = client.post(f"{URL}/{uploaded_id(client, ops)}/extract", headers=ops).json()["extraction"]["fields"]
    assert fields["invoice_number"] == "INV-1024"
    assert all(v is None for k, v in fields.items() if k != "invoice_number")


def test_every_extraction_is_ai_audited_without_document_content(client, ops, use_llm, db):
    use_llm(FakeLLM(json_response=GOOD_EXTRACTION))
    client.post(f"{URL}/{uploaded_id(client, ops)}/extract", headers=ops)
    log = db.scalar(select(AIAuditLog).where(AIAuditLog.operation_type == "EXTRACT"))
    assert log.status == "SUCCESS" and log.model_name == "fake-model" and log.duration_ms is not None
    assert "Extracted 9 of 9 fields" in log.response_summary
    blob = f"{log.request_summary} {log.response_summary} {log.details}"
    assert "Hydraulic pump" not in blob and "10,000.00" not in blob and "Harbor" not in blob  # no document text stored


def test_ollama_down_returns_503_and_the_document_can_be_retried(client, ops, use_llm, db):
    use_llm(FakeLLM(down=True))
    doc_id = uploaded_id(client, ops)
    resp = client.post(f"{URL}/{doc_id}/extract", headers=ops)
    assert resp.status_code == 503 and "not reachable" in resp.json()["detail"]
    detail = client.get(f"{URL}/{doc_id}", headers=ops).json()
    assert detail["extraction_status"] == "FAILED" and detail["extraction"] is None
    failed = db.scalar(select(AIAuditLog).where(AIAuditLog.status == "FAILED"))
    assert failed is not None and failed.operation_type == "EXTRACT"
    # Ollama comes back: the same document extracts normally
    use_llm(FakeLLM(json_response=GOOD_EXTRACTION))
    assert client.post(f"{URL}/{doc_id}/extract", headers=ops).json()["extraction_status"] == "COMPLETED"


def test_unusable_model_output_returns_502(client, ops, use_llm):
    def bad(*_):
        raise AIResponseError("The AI model returned something that was not valid JSON")

    use_llm(FakeLLM(json_response=bad))
    doc_id = uploaded_id(client, ops)
    assert client.post(f"{URL}/{doc_id}/extract", headers=ops).status_code == 502
    assert client.get(f"{URL}/{doc_id}", headers=ops).json()["extraction_status"] == "FAILED"


def test_a_document_being_extracted_cannot_be_extracted_again_at_the_same_time(client, ops, use_llm, db):
    from app.db.session import SessionLocal

    use_llm(FakeLLM(json_response=GOOD_EXTRACTION))
    doc_id = uploaded_id(client, ops)
    with SessionLocal() as other:  # simulates an extraction in progress holding the row lock
        other.execute(select(Document).where(Document.id == uuid.UUID(doc_id)).with_for_update())
        resp = client.post(f"{URL}/{doc_id}/extract", headers=ops)
    assert resp.status_code == 409 and "already being processed" in resp.json()["detail"]


def test_extract_unknown_document_is_404(client, ops, use_llm):
    use_llm(FakeLLM(json_response=GOOD_EXTRACTION))
    assert client.post(f"{URL}/{uuid.uuid4()}/extract", headers=ops).status_code == 404


def test_tampered_file_path_is_refused(client, ops, use_llm, db):
    use_llm(FakeLLM(json_response=GOOD_EXTRACTION))
    doc_id = uploaded_id(client, ops)
    doc = db.get(Document, uuid.UUID(doc_id))
    doc.file_path = "../../outside.pdf"
    db.commit()
    resp = client.post(f"{URL}/{doc_id}/extract", headers=ops)
    assert resp.status_code == 422 and "Invalid document path" in resp.json()["detail"]


def test_missing_stored_file_is_a_clean_404(client, ops, use_llm, upload_dir):
    use_llm(FakeLLM(json_response=GOOD_EXTRACTION))
    doc_id = uploaded_id(client, ops)
    for f in upload_dir.glob("*.pdf"):
        f.unlink()
    assert client.post(f"{URL}/{doc_id}/extract", headers=ops).status_code == 404


def test_re_extraction_is_allowed_until_verified(client, ops, use_llm):
    llm = use_llm(FakeLLM(json_response=GOOD_EXTRACTION))
    doc_id = uploaded_id(client, ops)
    client.post(f"{URL}/{doc_id}/extract", headers=ops)
    llm.json_response = {**GOOD_EXTRACTION, "invoice_number": "INV-1024"}
    assert client.post(f"{URL}/{doc_id}/extract", headers=ops).status_code == 200
    client.post(f"{URL}/{doc_id}/verify", json={"decision": "VERIFIED"}, headers=ops)
    assert client.post(f"{URL}/{doc_id}/extract", headers=ops).status_code == 409


# ======================================================================== human verification


def extracted(client, ops, use_llm, **kwargs) -> str:
    use_llm(FakeLLM(json_response=GOOD_EXTRACTION))
    doc_id = uploaded_id(client, ops, **kwargs)
    client.post(f"{URL}/{doc_id}/extract", headers=ops)
    return doc_id


def test_a_person_can_confirm_the_extracted_values(client, ops, use_llm, db):
    doc_id = extracted(client, ops, use_llm)
    resp = client.post(f"{URL}/{doc_id}/verify", json={"decision": "VERIFIED", "note": "Looks right"}, headers=ops)
    body = resp.json()
    assert resp.status_code == 200 and body["verification_status"] == "VERIFIED"
    assert body["confirmation"]["fields"]["invoice_amount"] == "10000.00"
    assert body["confirmation"]["by"] == "Olivia Operations" and body["confirmation"]["note"] == "Looks right"
    assert db.scalar(select(func.count()).select_from(Invoice)) == 0  # confirming still creates no financial record


def test_a_person_can_correct_values_and_the_changes_are_audited(client, ops, use_llm, db):
    doc_id = extracted(client, ops, use_llm)
    fields = {**GOOD_EXTRACTION, "invoice_amount": "10500.00"}
    fields.pop("confidence")
    resp = client.post(f"{URL}/{doc_id}/verify", json={"decision": "VERIFIED", "fields": fields}, headers=ops)
    body = resp.json()
    assert body["confirmation"]["fields"]["invoice_amount"] == "10500.00"
    assert body["extraction"]["fields"]["invoice_amount"] == "10000.00"  # the AI's draft is kept for the record
    log = db.scalar(select(AuditLog).where(AuditLog.action == "DOCUMENT_VERIFIED"))
    assert log.new_values["corrected_fields"]["invoice_amount"] == {"ai": "10000.00", "confirmed": "10500.00"}


@pytest.mark.parametrize(
    "bad",
    [{"invoice_amount": "-5"}, {"invoice_amount": "10.123"}, {"currency": "US"}, {"invoice_date": "not-a-date"}, {"document_type": "NOPE"}],
)
def test_confirmed_values_are_validated(client, ops, use_llm, bad):
    doc_id = extracted(client, ops, use_llm)
    fields = {k: v for k, v in GOOD_EXTRACTION.items() if k != "confidence"} | bad
    assert client.post(f"{URL}/{doc_id}/verify", json={"decision": "VERIFIED", "fields": fields}, headers=ops).status_code == 422


def test_cannot_verify_before_extraction(client, ops):
    doc_id = uploaded_id(client, ops)
    resp = client.post(f"{URL}/{doc_id}/verify", json={"decision": "VERIFIED"}, headers=ops)
    assert resp.status_code == 422 and "Extract the document first" in resp.json()["detail"]


def test_cannot_verify_twice(client, ops, use_llm):
    doc_id = extracted(client, ops, use_llm)
    client.post(f"{URL}/{doc_id}/verify", json={"decision": "VERIFIED"}, headers=ops)
    assert client.post(f"{URL}/{doc_id}/verify", json={"decision": "VERIFIED"}, headers=ops).status_code == 409
    assert client.post(f"{URL}/{doc_id}/verify", json={"decision": "REJECTED"}, headers=ops).status_code == 409


def test_a_document_can_be_rejected_even_without_extraction(client, ops, db):
    doc_id = uploaded_id(client, ops)
    body = client.post(f"{URL}/{doc_id}/verify", json={"decision": "REJECTED", "note": "Wrong file"}, headers=ops).json()
    assert body["verification_status"] == "REJECTED" and body["confirmation"]["note"] == "Wrong file"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "DOCUMENT_REJECTED")) is not None


def test_invalid_decision_is_rejected(client, ops):
    doc_id = uploaded_id(client, ops)
    assert client.post(f"{URL}/{doc_id}/verify", json={"decision": "MAYBE"}, headers=ops).status_code == 422


# ======================================================================== explanation


GROUNDED_SUMMARY = "Seven of nine fields were extracted. The invoice number is INV-1024 and the amount is 10,000.00 USD."


def test_explanation_compares_the_document_with_its_invoice(client, ops, use_llm, invoice):
    doc_id = extracted(client, ops, use_llm, invoice_id=invoice.id)
    use_llm(FakeLLM(text_response=rewrite_draft("In short: ")))
    body = client.post(f"{URL}/{doc_id}/explain", headers=ops).json()
    assert body["generated_by"] == "AI" and body["ai_note"] is None and body["summary"].startswith("In short: ")
    assert body["missing_fields"] == [] and body["needs_verification"] == []
    assert {f["status"] for f in body["findings"]} == {"MATCH"}
    assert len(body["findings"]) == 7  # number, exporter, buyer, currency, amount, two dates


def test_explanation_flags_differences_from_the_invoice(client, ops, use_llm, db, invoice):
    invoice.total_amount = Decimal("11000.00")
    invoice.currency = "USD"
    db.commit()
    doc_id = extracted(client, ops, use_llm, invoice_id=invoice.id)
    use_llm(FakeLLM(down=True))  # the deterministic result stands on its own
    body = client.post(f"{URL}/{doc_id}/explain", headers=ops).json()
    mismatch = [f for f in body["findings"] if f["status"] == "MISMATCH"]
    assert [f["field"] for f in mismatch] == ["invoice_amount"]
    assert mismatch[0]["document_value"] == "10,000.00" and mismatch[0]["invoice_value"] == "11,000.00"
    assert "1 difference(s) found" in body["summary"]


def test_explanation_falls_back_to_rules_when_ollama_is_down(client, ops, use_llm, db):
    doc_id = extracted(client, ops, use_llm)
    use_llm(FakeLLM(down=True))
    body = client.post(f"{URL}/{doc_id}/explain", headers=ops).json()
    assert body["generated_by"] == "RULES" and "unavailable" in body["ai_note"]
    assert "9 of 9 fields were extracted" in body["summary"]
    assert "not linked to an invoice" in body["summary"]
    assert db.scalar(select(AIAuditLog).where(AIAuditLog.operation_type == "EXPLAIN_DOCUMENT")).status == "UNAVAILABLE"


def test_ai_wording_with_invented_numbers_is_rejected(client, ops, use_llm, db):
    doc_id = extracted(client, ops, use_llm)
    use_llm(FakeLLM(text_response="The invoice total is 99,999.00 USD and is 42 days overdue."))
    body = client.post(f"{URL}/{doc_id}/explain", headers=ops).json()
    assert body["generated_by"] == "RULES" and "changed the document details" in body["ai_note"]
    assert "99,999" not in body["summary"]
    assert db.scalar(select(AIAuditLog).where(AIAuditLog.status == "REJECTED_UNGROUNDED")) is not None


def test_ai_wording_with_invented_references_is_rejected(client, ops, use_llm):
    doc_id = extracted(client, ops, use_llm)
    use_llm(FakeLLM(text_response="This relates to INV-7777 and looks fine."))
    assert client.post(f"{URL}/{doc_id}/explain", headers=ops).json()["generated_by"] == "RULES"


def test_explanation_reports_missing_and_unverifiable_fields(client, ops, use_llm):
    use_llm(FakeLLM(json_response={"invoice_number": "INV-1024", "buyer_name": "Imaginary Corp"}))
    doc_id = uploaded_id(client, ops)
    client.post(f"{URL}/{doc_id}/extract", headers=ops)
    use_llm(FakeLLM(down=True))
    body = client.post(f"{URL}/{doc_id}/explain", headers=ops).json()
    assert "Amount" in body["missing_fields"] and "Due date" in body["missing_fields"]
    assert body["needs_verification"] == ["Buyer"]


def test_explanation_requires_an_extraction(client, ops, use_llm):
    use_llm(FakeLLM(text_response="x"))
    doc_id = uploaded_id(client, ops)
    assert client.post(f"{URL}/{doc_id}/explain", headers=ops).status_code == 422
    assert client.post(f"{URL}/{uuid.uuid4()}/explain", headers=ops).status_code == 404


def test_explanation_prompt_contains_the_finished_summary_to_reword(client, ops, use_llm, invoice):
    doc_id = extracted(client, ops, use_llm, invoice_id=invoice.id)
    llm = use_llm(FakeLLM(text_response=rewrite_draft()))
    client.post(f"{URL}/{doc_id}/explain", headers=ops)
    prompt = llm.text_calls[0]
    assert "Keep EVERY" in prompt["system"] and "regulatory approval" in prompt["system"]
    assert "9 of 9 fields were extracted" in prompt["user"] and "INV-1024" in prompt["user"]


def test_a_rewrite_that_drops_a_difference_is_rejected(client, ops, use_llm, db, invoice):
    invoice.total_amount = Decimal("11000.00")
    db.commit()
    doc_id = extracted(client, ops, use_llm, invoice_id=invoice.id)
    # the draft says the document total (10,000.00) differs from the invoice (11,000.00); this rewrite hides that
    use_llm(FakeLLM(text_response="Everything looks fine for invoice INV-1024."))
    body = client.post(f"{URL}/{doc_id}/explain", headers=ops).json()
    assert body["generated_by"] == "RULES" and "10,000.00" in body["summary"] and "11,000.00" in body["summary"]


# ======================================================================== listing


def test_list_and_filter_documents(client, ops, invoice, use_llm):
    a = uploaded_id(client, ops, name="a.pdf", invoice_id=invoice.id)
    uploaded_id(client, ops, name="b.pdf", doc_type="PACKING_LIST")
    use_llm(FakeLLM(json_response=GOOD_EXTRACTION))
    client.post(f"{URL}/{a}/extract", headers=ops)

    def names(**params):
        return sorted(i["file_name"] for i in client.get(URL, params=params, headers=ops).json()["items"])

    assert names() == ["a.pdf", "b.pdf"]
    assert names(document_type="PACKING_LIST") == ["b.pdf"]
    assert names(extraction_status="COMPLETED") == ["a.pdf"]
    assert names(verification_status="UPLOADED") == ["b.pdf"]
    assert names(invoice_id=str(invoice.id)) == ["a.pdf"]
    assert names(search="INV-1024") == ["a.pdf"]
    assert names(search="b.p") == ["b.pdf"]
    per_invoice = client.get(f"{URL}/invoice/{invoice.id}", headers=ops).json()
    assert per_invoice["total"] == 1 and per_invoice["items"][0]["file_name"] == "a.pdf"


def test_get_unknown_or_malformed_document(client, ops):
    assert client.get(f"{URL}/{uuid.uuid4()}", headers=ops).status_code == 404
    assert client.get(f"{URL}/not-a-uuid", headers=ops).status_code == 422
