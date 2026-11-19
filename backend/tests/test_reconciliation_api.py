import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db.seed import seed_demo_data
from app.main import app
from app.models.audit import AuditLog
from app.models.enums import AllocationType, InvoiceStatus, ReconciliationStatus, ReviewDecision
from app.models.invoice import Invoice
from app.models.payment import Payment, PaymentAllocation, ReconciliationResult

URL = "/api/v1/reconciliation"
SAMPLE_PAYMENTS_CSV = Path(__file__).resolve().parents[2] / "sample_data" / "payments.csv"
D = Decimal


@pytest.fixture
def demo(db, client):
    """The full synthetic dataset from seed_data.py (15 invoices, 20 payments), not yet reconciled."""
    seed_demo_data(db)
    db.commit()


def run(client, headers):
    return client.post(f"{URL}/run", headers=headers)


def results_by_txn(client, headers) -> dict[str, dict]:
    items = client.get(URL, params={"page_size": 100}, headers=headers).json()["items"]
    return {i["transaction_reference"]: i for i in items}


def invoice_status_by_number(client, headers) -> dict[str, str]:
    items = client.get("/api/v1/invoices", params={"page_size": 100}, headers=headers).json()["items"]
    return {i["invoice_number"]: i["status"] for i in items}


def result_id(client, headers, txn: str) -> str:
    return results_by_txn(client, headers)[txn]["id"]


# ======================================================================= the full demo scenario


def test_run_on_demo_data_produces_every_expected_outcome(client, finance, demo):
    summary = run(client, finance)
    assert summary.status_code == 200
    body = summary.json()
    assert body["processed"] == 20 and body["allocations_created"] == 8
    assert body["counts"] == {
        "MATCHED": 4, "PARTIAL": 4, "MISMATCH": 3, "DUPLICATE": 2, "UNMATCHED": 5, "MANUAL_REVIEW": 2,
    }

    r = results_by_txn(client, finance)
    expected = {  # txn -> (status, invoice, allocated)
        "TXN-1001": ("MATCHED", "INV-1010", "12500.00"),
        "TXN-1002": ("MATCHED", "INV-1011", "8400.00"),
        "TXN-1003": ("MATCHED", "INV-1012", "6750.00"),
        "TXN-1004": ("PARTIAL", "INV-1024", "6000.00"),
        "TXN-1005": ("PARTIAL", "INV-1024", "3500.00"),
        "TXN-1006": ("PARTIAL", "INV-1014", "5000.00"),
        "TXN-1007": ("PARTIAL", "INV-1016", "30000.00"),
        "TXN-1008": ("MISMATCH", "INV-1017", "0.00"),  # EUR paid against a USD invoice
        "TXN-1009": ("MISMATCH", "INV-1018", "0.00"),  # USD paid against a EUR invoice
        "TXN-1010": ("DUPLICATE", None, "0.00"),
        "TXN-1011": ("DUPLICATE", None, "0.00"),
        "TXN-1012": ("UNMATCHED", None, "0.00"),
        "TXN-1013": ("UNMATCHED", None, "0.00"),
        "TXN-1014": ("UNMATCHED", None, "0.00"),
        "TXN-1015": ("UNMATCHED", None, "0.00"),
        "TXN-1016": ("UNMATCHED", None, "0.00"),
        "TXN-1017": ("MISMATCH", "INV-1022", "0.00"),  # reference matches, sender is a different company
        "TXN-1018": ("MANUAL_REVIEW", "INV-1015", "0.00"),  # no reference, name + amount resemble INV-1015
        "TXN-1019": ("MANUAL_REVIEW", "INV-1021", "0.00"),  # overpayment: 6,000 vs 5,200
        "TXN-1020": ("MATCHED", "INV-1019", "7800.00"),
    }
    assert len(r) == 20
    for txn, (status, invoice, allocated) in expected.items():
        assert (r[txn]["status"], r[txn]["invoice_number"], r[txn]["allocated_amount"]) == (status, invoice, allocated), txn

    # a currency mismatch shows the invoice in ITS currency, not the payment's
    assert (r["TXN-1008"]["currency"], r["TXN-1008"]["invoice_currency"]) == ("EUR", "USD")

    # BRD FR-017: INV-1024 is $10,000; 6,000 + 3,500 received -> 500 outstanding
    assert r["TXN-1005"]["previously_received"] == "6000.00"
    assert r["TXN-1005"]["outstanding_after"] == "500.00"
    assert r["TXN-1005"]["invoice_amount"] == "10000.00"
    assert r["TXN-1005"]["match_method"] == "EXACT_REFERENCE" and r["TXN-1005"]["confidence"] == "100.00"
    assert "outstanding" in r["TXN-1005"]["explanation"]

    # invoice statuses follow the allocations (overdue partials stay OVERDUE; see invoice_status.py)
    status = invoice_status_by_number(client, finance)
    assert {n for n, s in status.items() if s == "PAID"} == {"INV-1010", "INV-1011", "INV-1012", "INV-1019"}
    assert status["INV-1024"] == "PARTIALLY_PAID"
    assert {n for n, s in status.items() if s == "OVERDUE"} == {"INV-1013", "INV-1014", "INV-1015", "INV-1016", "INV-1020"}


def test_payment_statuses_are_updated(client, finance, demo, db):
    run(client, finance)
    db.expire_all()
    statuses = {p.transaction_reference: p.status for p in db.scalars(select(Payment))}
    assert statuses["TXN-1001"] == ReconciliationStatus.MATCHED
    assert statuses["TXN-1010"] == ReconciliationStatus.DUPLICATE
    assert ReconciliationStatus.PENDING not in statuses.values()


def test_second_run_changes_nothing(client, finance, demo, db):
    run(client, finance)
    allocations = db.scalar(select(func.count()).select_from(PaymentAllocation))
    again = run(client, finance).json()
    assert again == {"processed": 0, "counts": {}, "allocations_created": 0}
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(PaymentAllocation)) == allocations == 8
    assert db.scalar(select(func.count()).select_from(ReconciliationResult)) == 20


def test_run_with_nothing_pending_is_a_noop(client, finance):
    assert run(client, finance).json()["processed"] == 0


def test_money_invariants_hold_after_a_run(client, finance, demo, db):
    run(client, finance)
    over_paid = db.execute(text("""
        SELECT count(*) FROM payments p
        WHERE (SELECT COALESCE(SUM(allocated_amount),0) FROM payment_allocations a WHERE a.payment_id = p.id) > p.amount
    """)).scalar()
    over_billed = db.execute(text("""
        SELECT count(*) FROM invoices i
        WHERE (SELECT COALESCE(SUM(allocated_amount),0) FROM payment_allocations a WHERE a.invoice_id = i.id) > i.total_amount
    """)).scalar()
    cross_currency = db.execute(text("""
        SELECT count(*) FROM payment_allocations a
        JOIN payments p ON p.id = a.payment_id JOIN invoices i ON i.id = a.invoice_id
        WHERE a.currency <> p.currency OR a.currency <> i.currency
    """)).scalar()
    assert (over_paid, over_billed, cross_currency) == (0, 0, 0)
    # result records agree with the allocation ledger
    mismatches = db.execute(text("""
        SELECT count(*) FROM reconciliation_results r
        WHERE r.allocated_amount <> (SELECT COALESCE(SUM(allocated_amount),0) FROM payment_allocations a WHERE a.payment_id = r.payment_id)
    """)).scalar()
    assert mismatches == 0


def test_run_is_audited(client, finance, demo, db):
    run(client, finance)
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "PAYMENT_RECONCILED")) == 20
    log = db.scalar(select(AuditLog).where(AuditLog.action == "RECONCILIATION_RUN"))
    assert log.new_values["processed"] == 20 and log.new_values["allocations_created"] == 8


def test_new_import_is_reconciled_against_existing_state(client, finance, demo, db):
    """The sample bank file settles overdue invoices; duplicates of old payments are recognised."""
    run(client, finance)
    resp = client.post(
        "/api/v1/payments/import", files={"file": ("payments.csv", SAMPLE_PAYMENTS_CSV.read_bytes(), "text/csv")}, headers=finance
    )
    assert resp.json()["accepted_rows"] == 4
    second = run(client, finance).json()
    assert second["processed"] == 4 and second["counts"] == {"MATCHED": 4}

    status = invoice_status_by_number(client, finance)
    assert status["INV-1024"] == "PAID"  # 6,000 + 3,500 + 500
    assert status["INV-1014"] == "PAID"  # 5,000 + 10,200
    assert status["INV-1013"] == "PAID" and status["INV-1020"] == "PAID"
    r = results_by_txn(client, finance)
    assert r["TXN-2002"]["previously_received"] == "9500.00" and r["TXN-2002"]["outstanding_after"] == "0.00"


def test_a_resent_payment_in_a_later_batch_is_recognised_as_duplicate(client, finance, demo, db):
    run(client, finance)
    original = db.scalar(select(Payment).where(Payment.transaction_reference == "TXN-1001"))
    csv = (
        "transaction_reference,payment_reference,sender_name,currency,amount,transaction_date,bank_reference\n"
        f"TXN-9001,{original.payment_reference},{original.sender_name},{original.currency},{original.amount},{original.transaction_date},B\n"
    )
    client.post("/api/v1/payments/import", files={"file": ("late.csv", csv.encode(), "text/csv")}, headers=finance)
    assert run(client, finance).json()["counts"] == {"DUPLICATE": 1}


# ======================================================================= reading results


def test_list_summary_filters_and_detail(client, finance, demo):
    run(client, finance)
    summary = client.get(f"{URL}/summary", headers=finance).json()
    assert summary["total"] == 20 and summary["needs_review"] == 10  # 5 unmatched + 3 mismatch + 2 manual review
    assert summary["counts"]["MATCHED"] == 4

    assert client.get(URL, params={"status": "PARTIAL"}, headers=finance).json()["total"] == 4
    assert client.get(URL, params={"needs_review": True}, headers=finance).json()["total"] == 10
    by_invoice = client.get(URL, params={"search": "INV-1024"}, headers=finance).json()
    assert {i["transaction_reference"] for i in by_invoice["items"]} == {"TXN-1004", "TXN-1005"}
    assert client.get(URL, params={"search": "zenith"}, headers=finance).json()["total"] == 1

    page = client.get(URL, params={"page": 2, "page_size": 8}, headers=finance).json()
    assert page["total"] == 20 and page["pages"] == 3 and len(page["items"]) == 8

    detail = client.get(f"{URL}/{result_id(client, finance, 'TXN-1018')}", headers=finance).json()
    assert detail["status"] == "MANUAL_REVIEW" and detail["needs_review"] is True
    assert detail["candidates"][0]["invoice_number"] == "INV-1015"
    assert detail["candidates"][0]["outstanding"] == "9300.00"
    assert D(detail["confidence"]) <= D("80")
    assert detail["payment_unallocated"] == "9300.00"


def test_detail_404_and_bad_ids(client, finance):
    assert client.get(f"{URL}/{uuid.uuid4()}", headers=finance).status_code == 404
    assert client.get(f"{URL}/not-a-uuid", headers=finance).status_code == 422
    assert client.get(f"{URL}/{uuid.uuid4()}/eligible-invoices", headers=finance).status_code == 404


# ======================================================================= authorization


def test_unauthenticated_requests_return_401(client):
    assert client.post(f"{URL}/run").status_code == 401
    assert client.get(URL).status_code == 401
    assert client.get(f"{URL}/summary").status_code == 401


def test_operations_cannot_use_reconciliation(client, ops, finance, demo):
    run(client, finance)
    rid = result_id(client, finance, "TXN-1019")
    assert client.post(f"{URL}/run", headers=ops).status_code == 403
    assert client.get(URL, headers=ops).status_code == 403
    assert client.get(f"{URL}/{rid}", headers=ops).status_code == 403
    assert client.post(f"{URL}/{rid}/approve", json={"invoice_id": str(uuid.uuid4())}, headers=ops).status_code == 403
    assert client.post(f"{URL}/{rid}/reject", json={}, headers=ops).status_code == 403


def test_admin_can_run(client, admin, demo):
    assert run(client, admin).status_code == 200


# ======================================================================= manual approval


def invoice_id_for(db, number: str) -> str:
    return str(db.scalar(select(Invoice.id).where(Invoice.invoice_number == number)))


def test_manual_approval_of_an_overpayment_allocates_only_the_outstanding_amount(client, finance, demo, db):
    run(client, finance)
    rid = result_id(client, finance, "TXN-1019")  # 6,000 paid against INV-1021 of 5,200
    eligible = client.get(f"{URL}/{rid}/eligible-invoices", headers=finance).json()
    assert eligible[0]["invoice_number"] == "INV-1021" and eligible[0]["is_candidate"] is True

    resp = client.post(
        f"{URL}/{rid}/approve",
        json={"invoice_id": invoice_id_for(db, "INV-1021"), "note": "Customer confirmed the extra is a deposit"},
        headers=finance,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "MATCHED" and body["review_decision"] == "APPROVED"
    assert body["allocated_amount"] == "5200.00"  # never more than the invoice's outstanding balance
    assert body["payment_unallocated"] == "800.00"  # the excess stays visible and unallocated
    assert body["match_method"] == "MANUAL_APPROVAL" and body["reviewed_by_name"] == "Farhan Finance"
    assert body["review_note"] == "Customer confirmed the extra is a deposit"
    assert "Manually approved" in body["explanation"] and "800.00" in body["explanation"]
    assert body["needs_review"] is False

    db.expire_all()
    allocation = db.scalar(select(PaymentAllocation).join(Payment).where(Payment.transaction_reference == "TXN-1019"))
    assert allocation.allocation_type == AllocationType.MANUAL and allocation.allocated_amount == D("5200.00")
    assert invoice_status_by_number(client, finance)["INV-1021"] == "PAID"

    log = db.scalar(select(AuditLog).where(AuditLog.action == "RECONCILIATION_APPROVED"))
    assert log is not None and log.old_values["status"] == "MANUAL_REVIEW" and log.new_values["invoice_number"] == "INV-1021"


def test_manual_approval_of_a_partial_amount(client, finance, demo, db):
    run(client, finance)
    rid = result_id(client, finance, "TXN-1018")  # 9,300 against INV-1015 (9,300)
    resp = client.post(f"{URL}/{rid}/approve", json={"invoice_id": invoice_id_for(db, "INV-1015"), "amount": "4000.00"}, headers=finance)
    body = resp.json()
    assert resp.status_code == 200 and body["status"] == "PARTIAL"
    assert body["allocated_amount"] == "4000.00" and body["outstanding_after"] == "5300.00"
    assert body["payment_unallocated"] == "5300.00"


def test_unmatched_payment_can_be_allocated_manually(client, finance, demo, db):
    run(client, finance)
    rid = result_id(client, finance, "TXN-1016")  # 9,999.99 USD advance, no invoice
    inv = invoice_id_for(db, "INV-1017")  # a USD invoice
    resp = client.post(f"{URL}/{rid}/approve", json={"invoice_id": inv, "amount": "1000.00"}, headers=finance)
    assert resp.status_code == 200 and resp.json()["status"] == "PARTIAL"


def test_manual_approval_validations(client, finance, demo, db):
    run(client, finance)
    overpay = result_id(client, finance, "TXN-1019")
    inv_1021 = invoice_id_for(db, "INV-1021")

    def approve(rid, **body):
        return client.post(f"{URL}/{rid}/approve", json=body, headers=finance)

    # more than the invoice's outstanding balance
    too_much = approve(overpay, invoice_id=inv_1021, amount="5200.01")
    assert too_much.status_code == 422 and "too high" in too_much.json()["detail"]
    # non-positive and malformed amounts
    assert approve(overpay, invoice_id=inv_1021, amount="0").status_code == 422
    assert approve(overpay, invoice_id=inv_1021, amount="-5").status_code == 422
    assert approve(overpay, invoice_id=inv_1021, amount="1.234").status_code == 422
    # unknown invoice
    assert approve(overpay, invoice_id=str(uuid.uuid4())).status_code == 422
    # currency mismatch: EUR payment (TXN-1008) onto a USD invoice is refused outright
    eur_payment = result_id(client, finance, "TXN-1008")
    cross = approve(eur_payment, invoice_id=invoice_id_for(db, "INV-1017"))
    assert cross.status_code == 422 and "Currency mismatch" in cross.json()["detail"]
    # nothing was allocated by any failed attempt
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(PaymentAllocation)) == 8


def test_cannot_allocate_to_a_cancelled_or_settled_invoice(client, finance, demo, db):
    run(client, finance)
    rid = result_id(client, finance, "TXN-1019")
    settled = invoice_id_for(db, "INV-1010")  # PAID by TXN-1001
    assert client.post(f"{URL}/{rid}/approve", json={"invoice_id": settled}, headers=finance).status_code == 422
    inv = db.get(Invoice, uuid.UUID(invoice_id_for(db, "INV-1021")))
    inv.status = InvoiceStatus.CANCELLED
    db.commit()
    resp = client.post(f"{URL}/{rid}/approve", json={"invoice_id": str(inv.id)}, headers=finance)
    assert resp.status_code == 422 and "cancelled" in resp.json()["detail"]


def test_cannot_approve_twice_or_approve_resolved_results(client, finance, demo, db):
    run(client, finance)
    rid = result_id(client, finance, "TXN-1019")
    body = {"invoice_id": invoice_id_for(db, "INV-1021")}
    assert client.post(f"{URL}/{rid}/approve", json=body, headers=finance).status_code == 200
    assert client.post(f"{URL}/{rid}/approve", json=body, headers=finance).status_code == 409
    for txn in ("TXN-1001", "TXN-1010"):  # MATCHED and DUPLICATE are not reviewable
        resolved = result_id(client, finance, txn)
        assert client.post(f"{URL}/{resolved}/approve", json=body, headers=finance).status_code == 409


def test_approval_cannot_use_more_than_the_payment_has_left(client, finance, demo, db):
    run(client, finance)
    rid = result_id(client, finance, "TXN-1018")  # 9,300 GBP
    inv_1015 = invoice_id_for(db, "INV-1015")
    assert client.post(f"{URL}/{rid}/approve", json={"invoice_id": inv_1015, "amount": "9000.00"}, headers=finance).status_code == 200
    # the result is now resolved; a second allocation attempt is refused rather than double-spending the payment
    again = client.post(f"{URL}/{rid}/approve", json={"invoice_id": inv_1015, "amount": "9000.00"}, headers=finance)
    assert again.status_code == 409
    db.expire_all()
    paid = db.scalar(select(func.coalesce(func.sum(PaymentAllocation.allocated_amount), 0)).join(Payment).where(Payment.transaction_reference == "TXN-1018"))
    assert paid == D("9000.00")


def test_eligible_invoices_are_same_currency_payable_and_open(client, finance, demo, db):
    run(client, finance)
    rid = result_id(client, finance, "TXN-1016")  # USD
    eligible = client.get(f"{URL}/{rid}/eligible-invoices", headers=finance).json()
    numbers = {e["invoice_number"] for e in eligible}
    assert all(e["currency"] == "USD" for e in eligible)
    assert "INV-1017" in numbers and "INV-1024" in numbers
    assert "INV-1010" not in numbers  # fully paid
    assert "INV-1023" not in numbers  # draft
    assert "INV-1018" not in numbers  # EUR


# ======================================================================= manual rejection


def test_reject_a_suggested_candidate(client, finance, demo, db):
    run(client, finance)
    rid = result_id(client, finance, "TXN-1018")
    resp = client.post(f"{URL}/{rid}/reject", json={"note": "Different customer entity"}, headers=finance)
    body = resp.json()
    assert resp.status_code == 200
    assert body["status"] == "UNMATCHED" and body["review_decision"] == "REJECTED"
    assert body["invoice_number"] is None and body["review_note"] == "Different customer entity"
    assert "rejected by Farhan Finance" in body["explanation"]
    db.expire_all()
    assert db.scalar(select(Payment.status).where(Payment.transaction_reference == "TXN-1018")) == ReconciliationStatus.UNMATCHED
    log = db.scalar(select(AuditLog).where(AuditLog.action == "RECONCILIATION_REJECTED"))
    assert log.new_values["rejected_invoice"] == "INV-1015"


def test_reject_a_mismatch(client, finance, demo):
    run(client, finance)
    rid = result_id(client, finance, "TXN-1017")
    assert client.post(f"{URL}/{rid}/reject", json={}, headers=finance).json()["status"] == "UNMATCHED"


def test_only_unresolved_review_results_can_be_rejected(client, finance, demo):
    run(client, finance)
    rid = result_id(client, finance, "TXN-1018")
    assert client.post(f"{URL}/{rid}/reject", json={}, headers=finance).status_code == 200
    assert client.post(f"{URL}/{rid}/reject", json={}, headers=finance).status_code == 409  # already rejected
    for txn in ("TXN-1001", "TXN-1012", "TXN-1010"):  # matched, unmatched, duplicate
        assert client.post(f"{URL}/{result_id(client, finance, txn)}/reject", json={}, headers=finance).status_code == 409


def test_a_rejected_payment_can_still_be_allocated_manually(client, finance, demo, db):
    run(client, finance)
    rid = result_id(client, finance, "TXN-1018")
    client.post(f"{URL}/{rid}/reject", json={}, headers=finance)
    resp = client.post(f"{URL}/{rid}/approve", json={"invoice_id": invoice_id_for(db, "INV-1015")}, headers=finance)
    assert resp.status_code == 200 and resp.json()["status"] == "MATCHED"


# ======================================================================= database-level guards


def _raw_allocation(db, payment_txn: str, invoice_number: str, amount: str, currency: str = "USD") -> None:
    payment = db.scalar(select(Payment).where(Payment.transaction_reference == payment_txn))
    invoice = db.scalar(select(Invoice).where(Invoice.invoice_number == invoice_number))
    db.add(
        PaymentAllocation(
            payment_id=payment.id, invoice_id=invoice.id, allocated_amount=D(amount),
            currency=currency, allocation_type=AllocationType.MANUAL,
        )
    )
    db.flush()


def test_database_rejects_allocation_larger_than_the_payment(db, client, demo):
    with pytest.raises(IntegrityError, match="exceed the payment amount"):
        _raw_allocation(db, "TXN-1001", "INV-1010", "12500.01")  # payment is 12,500.00
    db.rollback()


def test_database_rejects_allocation_larger_than_the_invoice(db, client, demo):
    with pytest.raises(IntegrityError, match="exceed the invoice amount"):
        _raw_allocation(db, "TXN-1016", "INV-1019", "7800.01")  # USD invoice of 7,800.00; payment is 9,999.99
    db.rollback()


def test_database_rejects_cross_currency_allocation(db, client, demo):
    with pytest.raises(IntegrityError, match="currency"):
        _raw_allocation(db, "TXN-1008", "INV-1017", "100.00", currency="EUR")  # EUR payment, USD invoice
    db.rollback()
    with pytest.raises(IntegrityError, match="currency"):
        _raw_allocation(db, "TXN-1008", "INV-1017", "100.00", currency="USD")
    db.rollback()


def test_database_blocks_cumulative_over_allocation(db, client, demo):
    _raw_allocation(db, "TXN-1016", "INV-1019", "7000.00")
    with pytest.raises(IntegrityError, match="exceed the invoice amount"):
        _raw_allocation(db, "TXN-1016", "INV-1019", "800.01")
    db.rollback()


def test_allocations_are_append_only(db, client, finance, demo):
    run(client, finance)
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("UPDATE payment_allocations SET allocated_amount = allocated_amount + 1"))
    db.rollback()
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("DELETE FROM payment_allocations"))
    db.rollback()
    assert db.scalar(select(func.count()).select_from(PaymentAllocation)) == 8


# ======================================================================= concurrency


def test_concurrent_runs_never_process_a_payment_twice(client, finance, demo, db):
    barrier = Barrier(2)

    def go(_):
        local = TestClient(app)
        barrier.wait()
        return local.post(f"{URL}/run", headers=finance)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(go, range(2)))

    assert [r.status_code for r in responses] == [200, 200]
    assert sum(r.json()["processed"] for r in responses) == 20  # every payment handled exactly once
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(ReconciliationResult)) == 20
    assert db.scalar(select(func.count()).select_from(PaymentAllocation)) == 8
    assert db.scalar(select(func.count(func.distinct(ReconciliationResult.payment_id)))) == 20


def test_concurrent_approvals_allocate_only_once(client, finance, demo, db):
    run(client, finance)
    rid = result_id(client, finance, "TXN-1019")
    body = {"invoice_id": invoice_id_for(db, "INV-1021")}
    barrier = Barrier(2)

    def go(_):
        local = TestClient(app)
        barrier.wait()
        return local.post(f"{URL}/{rid}/approve", json=body, headers=finance)

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(r.status_code for r in pool.map(go, range(2)))

    assert codes == [200, 409]
    db.expire_all()
    total = db.scalar(select(func.sum(PaymentAllocation.allocated_amount)).join(Payment).where(Payment.transaction_reference == "TXN-1019"))
    assert total == D("5200.00")
