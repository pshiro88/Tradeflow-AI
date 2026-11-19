import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import app
from app.models.audit import AuditLog
from app.models.enums import AllocationType, InvoiceStatus, ReconciliationStatus
from app.models.invoice import Invoice
from app.models.party import Buyer, Exporter
from app.models.payment import Payment, PaymentAllocation
from app.services.invoice_status import derive_status

TODAY = date.today()
URL = "/api/v1/invoices"


@pytest.fixture
def exporter(db) -> Exporter:
    exp = Exporter(company_name="Test Exports Pvt Ltd", country="India")
    db.add(exp)
    db.commit()
    return exp


def payload(exporter: Exporter, **overrides) -> dict:
    base = {
        "invoice_number": "INV-5001",
        "exporter_id": str(exporter.id),
        "buyer_name": "Acme Imports LLC",
        "buyer_country": "USA",
        "invoice_date": (TODAY - timedelta(days=5)).isoformat(),
        "due_date": (TODAY + timedelta(days=25)).isoformat(),
        "currency": "USD",
        "total_amount": "10000.00",
        "description": "Test goods",
        "payment_terms": "Net 30",
    }
    base.update(overrides)
    return base


def create(client, headers, exporter, **overrides):
    return client.post(URL, json=payload(exporter, **overrides), headers=headers)


def add_payment(db, invoice_id: str, amount: str, currency: str = "USD", ref: str | None = None) -> None:
    """Simulate an allocation made by the reconciliation engine (built in a later step)."""
    pay = Payment(
        transaction_reference=ref or f"TXN-{uuid.uuid4().hex[:8]}",
        payment_reference="X",
        sender_name="Acme Imports LLC",
        currency=currency,
        amount=Decimal(amount),
        transaction_date=TODAY,
        status=ReconciliationStatus.MATCHED,
    )
    db.add(pay)
    db.flush()
    db.add(
        PaymentAllocation(
            payment_id=pay.id,
            invoice_id=uuid.UUID(invoice_id),
            allocated_amount=Decimal(amount),
            currency=currency,
            allocation_type=AllocationType.AUTO,
        )
    )
    db.commit()


# ------------------------------------------------------------------ create


def test_create_invoice_success(client, finance, exporter, db):
    resp = create(client, finance, exporter)
    assert resp.status_code == 201
    body = resp.json()
    assert body["invoice_number"] == "INV-5001"
    assert body["status"] == "OPEN"
    assert body["buyer_name"] == "Acme Imports LLC"
    assert body["amount_received"] == "0.00"
    assert body["outstanding_amount"] == "10000.00"
    assert body["has_payments"] is False
    assert body["is_editable"] is True
    # audit trail written in the same transaction
    log = db.scalar(select(AuditLog).where(AuditLog.action == "INVOICE_CREATED"))
    assert log is not None and log.new_values["invoice_number"] == "INV-5001"


def test_money_is_serialised_as_strings_not_floats(client, finance, exporter):
    body = create(client, finance, exporter, total_amount="12345.60").json()
    assert body["total_amount"] == "12345.60"
    assert isinstance(body["total_amount"], str)


def test_create_draft_invoice(client, finance, exporter):
    body = create(client, finance, exporter, status="DRAFT").json()
    assert body["status"] == "DRAFT"


def test_create_reuses_buyer_with_same_name_case_insensitively(client, finance, exporter, db):
    create(client, finance, exporter, invoice_number="INV-A", buyer_name="Acme Imports LLC")
    create(client, finance, exporter, invoice_number="INV-B", buyer_name="ACME IMPORTS llc")
    assert db.scalar(select(func.count()).select_from(Buyer)) == 1


def test_duplicate_invoice_number_returns_409_case_insensitive(client, finance, exporter):
    assert create(client, finance, exporter, invoice_number="INV-9").status_code == 201
    resp = create(client, finance, exporter, invoice_number="inv-9")
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"total_amount": "-5.00"},
        {"total_amount": "0"},
        {"total_amount": "10.123"},
        {"currency": "JPY"},
        {"invoice_number": "   "},
        {"buyer_name": ""},
        {"due_date": (TODAY - timedelta(days=30)).isoformat()},  # before invoice date
        {"invoice_date": "not-a-date"},
    ],
)
def test_create_validation_errors_return_422(client, finance, exporter, overrides):
    assert create(client, finance, exporter, **overrides).status_code == 422


def test_create_with_unknown_exporter_returns_422(client, finance, exporter):
    resp = create(client, finance, exporter, exporter_id=str(uuid.uuid4()))
    assert resp.status_code == 422


def test_currency_is_normalised_to_uppercase(client, finance, exporter):
    assert create(client, finance, exporter, currency="eur").json()["currency"] == "EUR"


# ------------------------------------------------------------------ authorization


def test_unauthenticated_requests_return_401(client, exporter):
    assert client.get(URL).status_code == 401
    assert client.post(URL, json=payload(exporter)).status_code == 401


def test_operations_can_read_but_not_write(client, finance, ops, exporter):
    inv_id = create(client, finance, exporter).json()["id"]
    assert client.get(URL, headers=ops).status_code == 200
    assert client.get(f"{URL}/{inv_id}", headers=ops).status_code == 200
    assert client.post(URL, json=payload(exporter, invoice_number="X-1"), headers=ops).status_code == 403
    assert client.put(f"{URL}/{inv_id}", json=payload(exporter), headers=ops).status_code == 403
    assert client.patch(f"{URL}/{inv_id}/status", json={"status": "CANCELLED"}, headers=ops).status_code == 403


def test_admin_can_write(client, admin, exporter):
    assert create(client, admin, exporter).status_code == 201


def test_there_is_no_delete_endpoint(client, finance, exporter):
    inv_id = create(client, finance, exporter).json()["id"]
    assert client.delete(f"{URL}/{inv_id}", headers=finance).status_code == 405


# ------------------------------------------------------------------ list / search / filter / paginate


def seed_many(client, finance, exporter, n=5):
    for i in range(n):
        create(
            client, finance, exporter,
            invoice_number=f"INV-{7000 + i}",
            buyer_name="Alpha Buyer" if i % 2 == 0 else "Beta Buyer",
            currency="USD" if i % 2 == 0 else "EUR",
            total_amount=f"{1000 * (i + 1)}.00",
            invoice_date=(TODAY - timedelta(days=i)).isoformat(),
            due_date=(TODAY + timedelta(days=30)).isoformat(),
        )


def test_list_pagination(client, finance, exporter):
    seed_many(client, finance, exporter, 5)
    page1 = client.get(URL, params={"page": 1, "page_size": 2}, headers=finance).json()
    assert page1["total"] == 5 and page1["pages"] == 3 and len(page1["items"]) == 2
    page3 = client.get(URL, params={"page": 3, "page_size": 2}, headers=finance).json()
    assert len(page3["items"]) == 1
    assert page1["items"][0]["id"] != page3["items"][0]["id"]


def test_list_rejects_bad_pagination(client, finance):
    assert client.get(URL, params={"page": 0}, headers=finance).status_code == 422
    assert client.get(URL, params={"page_size": 1000}, headers=finance).status_code == 422


def test_list_search_by_invoice_number_and_buyer(client, finance, exporter):
    seed_many(client, finance, exporter, 4)
    by_number = client.get(URL, params={"search": "7002"}, headers=finance).json()
    assert [i["invoice_number"] for i in by_number["items"]] == ["INV-7002"]
    by_buyer = client.get(URL, params={"search": "beta"}, headers=finance).json()
    assert by_buyer["total"] == 2


def test_list_filters_currency_and_date(client, finance, exporter):
    seed_many(client, finance, exporter, 4)
    eur = client.get(URL, params={"currency": "EUR"}, headers=finance).json()
    assert eur["total"] == 2 and all(i["currency"] == "EUR" for i in eur["items"])
    recent = client.get(URL, params={"date_from": (TODAY - timedelta(days=1)).isoformat()}, headers=finance).json()
    assert recent["total"] == 2


def test_list_sorting(client, finance, exporter):
    seed_many(client, finance, exporter, 3)
    asc = client.get(URL, params={"sort_by": "total_amount", "sort_dir": "asc"}, headers=finance).json()["items"]
    amounts = [Decimal(i["total_amount"]) for i in asc]
    assert amounts == sorted(amounts)
    desc = client.get(URL, params={"sort_by": "total_amount", "sort_dir": "desc"}, headers=finance).json()["items"]
    assert [Decimal(i["total_amount"]) for i in desc] == sorted(amounts, reverse=True)


# ------------------------------------------------------------------ derived status


def test_status_open_overdue_partial_paid(client, finance, exporter, db):
    open_id = create(client, finance, exporter, invoice_number="S-OPEN").json()["id"]
    overdue = create(
        client, finance, exporter, invoice_number="S-OVERDUE",
        invoice_date=(TODAY - timedelta(days=60)).isoformat(), due_date=(TODAY - timedelta(days=10)).isoformat(),
    ).json()
    partial_id = create(client, finance, exporter, invoice_number="S-PARTIAL").json()["id"]
    paid_id = create(client, finance, exporter, invoice_number="S-PAID").json()["id"]

    assert overdue["status"] == "OVERDUE"
    add_payment(db, partial_id, "4000.00")
    add_payment(db, paid_id, "10000.00")

    status = lambda i: client.get(f"{URL}/{i}", headers=finance).json()  # noqa: E731
    assert status(open_id)["status"] == "OPEN"
    partial = status(partial_id)
    assert partial["status"] == "PARTIALLY_PAID"
    assert partial["amount_received"] == "4000.00" and partial["outstanding_amount"] == "6000.00"
    assert status(paid_id)["status"] == "PAID"
    assert status(paid_id)["outstanding_amount"] == "0.00"


def test_partially_paid_and_past_due_is_overdue(client, finance, exporter, db):
    inv = create(
        client, finance, exporter,
        invoice_date=(TODAY - timedelta(days=60)).isoformat(), due_date=(TODAY - timedelta(days=5)).isoformat(),
    ).json()
    add_payment(db, inv["id"], "2500.00")
    detail = client.get(f"{URL}/{inv['id']}", headers=finance).json()
    assert detail["status"] == "OVERDUE"
    assert detail["outstanding_amount"] == "7500.00"  # the partial payment is still visible


def test_overdue_payment_settles_past_due_invoice_to_paid(client, finance, exporter, db):
    inv = create(
        client, finance, exporter,
        invoice_date=(TODAY - timedelta(days=60)).isoformat(), due_date=(TODAY - timedelta(days=5)).isoformat(),
    ).json()
    add_payment(db, inv["id"], "10000.00")
    assert client.get(f"{URL}/{inv['id']}", headers=finance).json()["status"] == "PAID"


def test_status_filter_uses_derived_status(client, finance, exporter, db):
    create(client, finance, exporter, invoice_number="F-OPEN")
    create(
        client, finance, exporter, invoice_number="F-OVERDUE",
        invoice_date=(TODAY - timedelta(days=60)).isoformat(), due_date=(TODAY - timedelta(days=10)).isoformat(),
    )
    paid = create(client, finance, exporter, invoice_number="F-PAID").json()["id"]
    add_payment(db, paid, "10000.00")

    def numbers(status):
        data = client.get(URL, params={"status": status}, headers=finance).json()
        return sorted(i["invoice_number"] for i in data["items"])

    assert numbers("OPEN") == ["F-OPEN"]
    assert numbers("OVERDUE") == ["F-OVERDUE"]
    assert numbers("PAID") == ["F-PAID"]


def test_sql_status_matches_python_derive_status(client, finance, exporter, db):
    """The SQL CASE expression and derive_status() must never disagree."""
    scenarios = [
        ("P-1", -2, "0"), ("P-2", 20, "0"), ("P-3", 20, "3000.00"), ("P-4", -2, "3000.00"),
        ("P-5", 20, "10000.00"), ("P-6", -2, "10000.00"),
    ]
    for number, due_offset, paid in scenarios:
        inv = create(
            client, finance, exporter, invoice_number=number,
            invoice_date=(TODAY - timedelta(days=60)).isoformat(), due_date=(TODAY + timedelta(days=due_offset)).isoformat(),
        ).json()
        if Decimal(paid) > 0:
            add_payment(db, inv["id"], paid)

    for item in client.get(URL, params={"page_size": 100}, headers=finance).json()["items"]:
        invoice = db.get(Invoice, uuid.UUID(item["id"]))
        expected = derive_status(
            InvoiceStatus.OPEN, invoice.total_amount, Decimal(item["amount_received"]), invoice.due_date, TODAY
        )
        assert item["status"] == expected.value, item["invoice_number"]


@pytest.mark.parametrize(
    ("stored", "received", "due_offset", "expected"),
    [
        (InvoiceStatus.OPEN, "0", 10, InvoiceStatus.OPEN),
        (InvoiceStatus.OPEN, "0", -1, InvoiceStatus.OVERDUE),
        (InvoiceStatus.OPEN, "1", 10, InvoiceStatus.PARTIALLY_PAID),
        (InvoiceStatus.OPEN, "1", -1, InvoiceStatus.OVERDUE),
        (InvoiceStatus.OPEN, "100", -1, InvoiceStatus.PAID),
        (InvoiceStatus.OPEN, "100", 10, InvoiceStatus.PAID),
        (InvoiceStatus.OPEN, "0", 0, InvoiceStatus.OPEN),  # due today is not overdue yet
        (InvoiceStatus.DRAFT, "0", -30, InvoiceStatus.DRAFT),
        (InvoiceStatus.CANCELLED, "100", -30, InvoiceStatus.CANCELLED),
    ],
)
def test_derive_status_rules(stored, received, due_offset, expected):
    assert derive_status(stored, Decimal("100"), Decimal(received), TODAY + timedelta(days=due_offset), TODAY) == expected


# ------------------------------------------------------------------ detail


def test_detail_includes_payment_history(client, finance, exporter, db):
    inv = create(client, finance, exporter).json()
    add_payment(db, inv["id"], "6000.00", ref="TXN-A")
    add_payment(db, inv["id"], "3500.00", ref="TXN-B")
    detail = client.get(f"{URL}/{inv['id']}", headers=finance).json()
    assert detail["has_payments"] is True
    assert [p["transaction_reference"] for p in detail["payments"]] == ["TXN-A", "TXN-B"]
    assert detail["amount_received"] == "9500.00"
    assert detail["outstanding_amount"] == "500.00"


def test_get_unknown_invoice_returns_404(client, finance):
    assert client.get(f"{URL}/{uuid.uuid4()}", headers=finance).status_code == 404


def test_get_invalid_uuid_returns_422(client, finance):
    assert client.get(f"{URL}/not-a-uuid", headers=finance).status_code == 422


# ------------------------------------------------------------------ update


def test_update_invoice_and_audit(client, finance, exporter, db):
    inv = create(client, finance, exporter).json()
    resp = client.put(
        f"{URL}/{inv['id']}",
        json=payload(exporter, total_amount="11000.00", description="Revised", buyer_name="Acme Imports LLC"),
        headers=finance,
    )
    assert resp.status_code == 200
    assert resp.json()["total_amount"] == "11000.00" and resp.json()["description"] == "Revised"
    log = db.scalar(select(AuditLog).where(AuditLog.action == "INVOICE_UPDATED"))
    assert log.old_values["total_amount"] == "10000.00" and log.new_values["total_amount"] == "11000.00"


def test_update_to_existing_number_returns_409(client, finance, exporter):
    create(client, finance, exporter, invoice_number="U-1")
    other = create(client, finance, exporter, invoice_number="U-2").json()
    resp = client.put(f"{URL}/{other['id']}", json=payload(exporter, invoice_number="U-1"), headers=finance)
    assert resp.status_code == 409


def test_update_keeping_own_number_is_allowed(client, finance, exporter):
    inv = create(client, finance, exporter, invoice_number="U-3").json()
    resp = client.put(f"{URL}/{inv['id']}", json=payload(exporter, invoice_number="U-3"), headers=finance)
    assert resp.status_code == 200


def test_update_unknown_invoice_returns_404(client, finance, exporter):
    assert client.put(f"{URL}/{uuid.uuid4()}", json=payload(exporter), headers=finance).status_code == 404


def test_cancelled_invoice_cannot_be_edited(client, finance, exporter):
    inv = create(client, finance, exporter).json()
    client.patch(f"{URL}/{inv['id']}/status", json={"status": "CANCELLED"}, headers=finance)
    resp = client.put(f"{URL}/{inv['id']}", json=payload(exporter), headers=finance)
    assert resp.status_code == 409


def test_invoice_with_payments_locks_currency_buyer_and_number(client, finance, exporter, db):
    inv = create(client, finance, exporter).json()
    add_payment(db, inv["id"], "4000.00")
    for override in ({"currency": "EUR"}, {"buyer_name": "Different Buyer"}, {"invoice_number": "INV-CHANGED"}):
        resp = client.put(f"{URL}/{inv['id']}", json=payload(exporter, **override), headers=finance)
        assert resp.status_code == 409, override


def test_cannot_reduce_amount_below_received(client, finance, exporter, db):
    inv = create(client, finance, exporter).json()
    add_payment(db, inv["id"], "4000.00")
    resp = client.put(f"{URL}/{inv['id']}", json=payload(exporter, total_amount="3999.99"), headers=finance)
    assert resp.status_code == 422
    # reducing to exactly the received amount is fine and settles the invoice
    resp = client.put(f"{URL}/{inv['id']}", json=payload(exporter, total_amount="4000.00"), headers=finance)
    assert resp.status_code == 200 and resp.json()["status"] == "PAID"


def test_can_increase_amount_on_invoice_with_payments(client, finance, exporter, db):
    inv = create(client, finance, exporter).json()
    add_payment(db, inv["id"], "10000.00")
    resp = client.put(f"{URL}/{inv['id']}", json=payload(exporter, total_amount="12000.00"), headers=finance)
    assert resp.status_code == 200
    assert resp.json()["status"] == "PARTIALLY_PAID" and resp.json()["outstanding_amount"] == "2000.00"


# ------------------------------------------------------------------ status transitions


def test_publish_draft(client, finance, exporter, db):
    inv = create(client, finance, exporter, status="DRAFT").json()
    resp = client.patch(f"{URL}/{inv['id']}/status", json={"status": "OPEN"}, headers=finance)
    assert resp.status_code == 200 and resp.json()["status"] == "OPEN"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "INVOICE_PUBLISHED")) is not None


def test_cannot_publish_non_draft(client, finance, exporter):
    inv = create(client, finance, exporter).json()
    resp = client.patch(f"{URL}/{inv['id']}/status", json={"status": "OPEN"}, headers=finance)
    assert resp.status_code == 409


def test_cancel_invoice_without_payments(client, finance, exporter, db):
    inv = create(client, finance, exporter).json()
    resp = client.patch(f"{URL}/{inv['id']}/status", json={"status": "CANCELLED"}, headers=finance)
    assert resp.status_code == 200 and resp.json()["status"] == "CANCELLED"
    assert resp.json()["is_editable"] is False
    assert db.scalar(select(AuditLog).where(AuditLog.action == "INVOICE_CANCELLED")) is not None


def test_cannot_cancel_invoice_with_payments(client, finance, exporter, db):
    inv = create(client, finance, exporter).json()
    add_payment(db, inv["id"], "100.00")
    resp = client.patch(f"{URL}/{inv['id']}/status", json={"status": "CANCELLED"}, headers=finance)
    assert resp.status_code == 409
    assert client.get(f"{URL}/{inv['id']}", headers=finance).json()["status"] == "PARTIALLY_PAID"


def test_cannot_cancel_twice(client, finance, exporter):
    inv = create(client, finance, exporter).json()
    client.patch(f"{URL}/{inv['id']}/status", json={"status": "CANCELLED"}, headers=finance)
    resp = client.patch(f"{URL}/{inv['id']}/status", json={"status": "CANCELLED"}, headers=finance)
    assert resp.status_code == 409


@pytest.mark.parametrize("bad_status", ["PAID", "PARTIALLY_PAID", "OVERDUE", "DRAFT", "NOPE"])
def test_derived_statuses_cannot_be_set_manually(client, finance, exporter, bad_status):
    inv = create(client, finance, exporter).json()
    resp = client.patch(f"{URL}/{inv['id']}/status", json={"status": bad_status}, headers=finance)
    assert resp.status_code == 422


# ------------------------------------------------------------------ parties


def test_parties_endpoints(client, finance, exporter):
    create(client, finance, exporter)
    exporters = client.get(f"{URL}/exporters", headers=finance).json()
    buyers = client.get(f"{URL}/buyers", headers=finance).json()
    assert exporters[0]["name"] == "Test Exports Pvt Ltd"
    assert buyers[0]["name"] == "Acme Imports LLC" and buyers[0]["country"] == "USA"
