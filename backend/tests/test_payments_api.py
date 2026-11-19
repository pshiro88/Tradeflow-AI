import csv
import io
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.seed import seed_demo_data
from app.models.audit import AuditLog
from app.models.enums import AllocationType, ReconciliationStatus
from app.models.invoice import Invoice
from app.models.party import Buyer, Exporter
from app.models.payment import ImportBatch, Payment, PaymentAllocation
from app.repositories.payment_repository import PaymentRepository
from app.services.payment_import import ValidRow

TODAY = date.today()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()
HEADER = "transaction_reference,payment_reference,sender_name,currency,amount,transaction_date,bank_reference"
SAMPLE_PAYMENTS_CSV = Path(__file__).resolve().parents[2] / "sample_data" / "payments.csv"


def line(ref="TXN-1", pay="INV-1", sender="Acme LLC", cur="USD", amount="100.00", day=YESTERDAY, bank="B-1") -> str:
    return f"{ref},{pay},{sender},{cur},{amount},{day},{bank}"


def csv_bytes(*lines: str) -> bytes:
    return ("\n".join([HEADER, *lines]) + "\n").encode("utf-8")


def upload(client, headers, content: bytes, name: str = "bank.csv"):
    return client.post("/api/v1/payments/import", files={"file": (name, content, "text/csv")}, headers=headers)


def payment_count(db) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(Payment))


# ------------------------------------------------------------------ import: happy path


def test_import_valid_file(client, finance, db):
    resp = upload(client, finance, csv_bytes(line("TXN-1", amount="100.50"), line("TXN-2", sender="Beta Ltd", cur="EUR")))
    assert resp.status_code == 201
    body = resp.json()
    assert (body["total_rows"], body["accepted_rows"], body["rejected_rows"], body["duplicate_rows"]) == (2, 2, 0, 0)
    assert body["errors"] == []
    stored = {p.transaction_reference: p for p in db.scalars(select(Payment))}
    assert stored["TXN-1"].amount == Decimal("100.50")
    assert stored["TXN-1"].status == ReconciliationStatus.PENDING
    assert stored["TXN-2"].currency == "EUR"
    assert all(p.import_batch_id == uuid.UUID(body["id"]) for p in stored.values())


def test_import_writes_audit_log(client, finance, db):
    upload(client, finance, csv_bytes(line()))
    log = db.scalar(select(AuditLog).where(AuditLog.action == "PAYMENTS_IMPORTED"))
    assert log is not None and log.new_values["accepted_rows"] == 1 and log.new_values["file_name"] == "bank.csv"


# ------------------------------------------------------------------ import: partial acceptance and reporting


def test_invalid_rows_are_rejected_valid_rows_still_imported(client, finance, db):
    content = csv_bytes(
        line("TXN-OK"),
        line("TXN-BADCUR", cur="XYZ"),
        line("TXN-BADAMT", amount='"12,5"'),
        line("TXN-BADDATE", day="31-13-2026"),
        line("TXN-NOSENDER", sender=""),
    )
    body = upload(client, finance, content).json()
    assert (body["accepted_rows"], body["rejected_rows"], body["duplicate_rows"]) == (1, 4, 0)
    assert payment_count(db) == 1
    by_ref = {e["transaction_reference"]: e for e in body["errors"]}
    assert by_ref["TXN-BADCUR"]["issues"][0]["field"] == "currency"
    assert by_ref["TXN-BADAMT"]["issues"][0]["field"] == "amount"
    assert by_ref["TXN-BADDATE"]["issues"][0]["field"] == "transaction_date"
    assert by_ref["TXN-NOSENDER"]["issues"][0]["field"] == "sender_name"
    assert all(e["category"] == "VALIDATION" for e in body["errors"])


def test_error_rows_report_file_line_numbers(client, finance):
    body = upload(client, finance, csv_bytes(line("A"), line("B", cur="XYZ"), line("C"))).json()
    assert [e["row"] for e in body["errors"]] == [3]  # header is line 1


def test_duplicate_within_the_same_file(client, finance, db):
    body = upload(client, finance, csv_bytes(line("TXN-1"), line("TXN-2"), line("TXN-1", amount="999.00"))).json()
    assert (body["accepted_rows"], body["duplicate_rows"], body["rejected_rows"]) == (2, 1, 0)
    assert body["errors"][0]["category"] == "DUPLICATE_IN_FILE" and body["errors"][0]["row"] == 4
    # the FIRST occurrence wins
    assert db.scalar(select(Payment.amount).where(Payment.transaction_reference == "TXN-1")) == Decimal("100.00")


def test_duplicate_of_an_already_imported_transaction(client, finance, db):
    upload(client, finance, csv_bytes(line("TXN-1", amount="100.00")))
    body = upload(client, finance, csv_bytes(line("TXN-1", amount="555.00"), line("TXN-2"))).json()
    assert (body["accepted_rows"], body["duplicate_rows"]) == (1, 1)
    assert body["errors"][0]["category"] == "DUPLICATE_EXISTING"
    assert payment_count(db) == 2
    # the existing record was NOT overwritten
    assert db.scalar(select(Payment.amount).where(Payment.transaction_reference == "TXN-1")) == Decimal("100.00")


def test_importing_the_same_file_twice_creates_no_duplicates(client, finance, db):
    content = csv_bytes(line("TXN-1"), line("TXN-2"), line("TXN-3", cur="XYZ"))
    first = upload(client, finance, content).json()
    assert first["accepted_rows"] == 2
    second = upload(client, finance, content).json()
    assert (second["accepted_rows"], second["duplicate_rows"], second["rejected_rows"]) == (0, 2, 1)
    assert payment_count(db) == 2


def test_reference_matching_is_exact_not_case_folded(client, finance, db):
    """Documented behaviour: 'txn-1' and 'TXN-1' are different references."""
    body = upload(client, finance, csv_bytes(line("TXN-1"), line("txn-1"))).json()
    assert body["accepted_rows"] == 2


def test_bulk_insert_skips_conflicts_safely(db, client):
    """The ON CONFLICT guard: even if the pre-check missed a duplicate (a concurrent import), nothing breaks."""
    batch = ImportBatch(file_name="x.csv")
    db.add(batch)
    db.flush()

    def vr(ref: str) -> ValidRow:
        return ValidRow(2, ref, None, "S", "USD", Decimal("1.00"), TODAY, None)

    repo = PaymentRepository(db)
    assert repo.bulk_insert([vr("A"), vr("B")], batch.id) == {"A", "B"}
    assert repo.bulk_insert([vr("B"), vr("C")], batch.id) == {"C"}
    db.commit()
    assert payment_count(db) == 3


# ------------------------------------------------------------------ import: the real sample file


def test_sample_payments_csv_demonstrates_every_outcome(client, finance, db):
    assert SAMPLE_PAYMENTS_CSV.exists(), "run `python -m app.db.seed --write-csv`"
    seed_demo_data(db)
    db.commit()
    before = payment_count(db)
    body = upload(client, finance, SAMPLE_PAYMENTS_CSV.read_bytes(), "payments.csv").json()
    assert body["total_rows"] == 10
    assert body["accepted_rows"] == 4  # new valid transactions
    assert body["duplicate_rows"] == 2  # TXN-1003 and TXN-1007 already in the database
    assert body["rejected_rows"] == 4  # bad currency, amount, date and a missing sender
    assert payment_count(db) == before + 4
    # and importing it again changes nothing
    again = upload(client, finance, SAMPLE_PAYMENTS_CSV.read_bytes(), "payments.csv").json()
    assert again["accepted_rows"] == 0 and payment_count(db) == before + 4


# ------------------------------------------------------------------ import: file-level validation


def test_non_csv_extension_is_rejected(client, finance):
    resp = upload(client, finance, csv_bytes(line()), "bank.xlsx")
    assert resp.status_code == 422 and ".csv" in resp.json()["detail"]


def test_empty_file_is_rejected(client, finance):
    assert upload(client, finance, b"").status_code == 422


def test_header_only_file_is_rejected(client, finance):
    resp = upload(client, finance, (HEADER + "\n").encode())
    assert resp.status_code == 422 and "no transactions" in resp.json()["detail"]


def test_missing_required_column_is_rejected_without_creating_a_batch(client, finance, db):
    resp = upload(client, finance, b"transaction_reference,amount\nTXN-1,10\n")
    assert resp.status_code == 422 and "Missing required column" in resp.json()["detail"]
    assert db.scalar(select(func.count()).select_from(ImportBatch)) == 0


def test_non_utf8_file_is_rejected(client, finance):
    assert upload(client, finance, b"\xff\xfe\x00\x00garbage").status_code == 422


def test_oversized_file_returns_413(client, finance, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    resp = upload(client, finance, csv_bytes(line()))
    assert resp.status_code == 413


def test_row_limit_returns_422(client, finance, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_import_rows", 2)
    resp = upload(client, finance, csv_bytes(line("A"), line("B"), line("C")))
    assert resp.status_code == 422 and "Too many rows" in resp.json()["detail"]


def test_missing_file_field_returns_422(client, finance):
    assert client.post("/api/v1/payments/import", headers=finance).status_code == 422


def test_path_components_in_file_name_are_stripped(client, finance):
    body = upload(client, finance, csv_bytes(line()), "../../etc/passwd.csv").json()
    assert body["file_name"] == "passwd.csv"
    body = upload(client, finance, csv_bytes(line("TXN-2")), "C:\\Users\\x\\evil.csv").json()
    assert body["file_name"] == "evil.csv"


# ------------------------------------------------------------------ batches and error report


def test_batch_detail_and_recent_batches(client, finance):
    batch = upload(client, finance, csv_bytes(line("A"), line("B", cur="XYZ"))).json()
    detail = client.get(f"/api/v1/payments/imports/{batch['id']}", headers=finance).json()
    assert detail["rejected_rows"] == 1 and len(detail["errors"]) == 1
    recent = client.get("/api/v1/payments/imports", headers=finance).json()
    assert recent[0]["id"] == batch["id"] and "errors" not in recent[0]


def test_unknown_batch_returns_404(client, finance):
    assert client.get(f"/api/v1/payments/imports/{uuid.uuid4()}", headers=finance).status_code == 404
    assert client.get(f"/api/v1/payments/imports/{uuid.uuid4()}/errors.csv", headers=finance).status_code == 404


def test_error_report_csv(client, finance):
    batch = upload(client, finance, csv_bytes(line("GOOD"), line("BAD", cur="XYZ", sender="Evil Co"))).json()
    resp = client.get(f"/api/v1/payments/imports/{batch['id']}/errors.csv", headers=finance)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[0][:4] == ["row_number", "category", "issues", "transaction_reference"]
    assert len(rows) == 2
    assert rows[1][:2] == ["3", "VALIDATION"] and rows[1][2].startswith("currency:")
    assert rows[1][3] == "BAD" and "GOOD" not in resp.text


def test_error_report_neutralises_spreadsheet_formulas(client, finance):
    evil = '=HYPERLINK("http://evil.example","click")'
    batch = upload(client, finance, csv_bytes(f'TXN-X,INV-1,"{evil}",XYZ,10,{YESTERDAY},B')).json()
    report = client.get(f"/api/v1/payments/imports/{batch['id']}/errors.csv", headers=finance).text
    assert "'=HYPERLINK" in report
    assert "\r\n=HYPERLINK" not in report and ",=HYPERLINK" not in report


# ------------------------------------------------------------------ authorization


def test_unauthenticated_requests_return_401(client):
    assert client.get("/api/v1/payments").status_code == 401
    assert client.post("/api/v1/payments/import", files={"file": ("a.csv", b"x", "text/csv")}).status_code == 401


def test_operations_cannot_access_payments(client, ops):
    assert client.get("/api/v1/payments", headers=ops).status_code == 403
    assert upload(client, ops, csv_bytes(line())).status_code == 403
    assert client.get("/api/v1/payments/imports", headers=ops).status_code == 403


def test_admin_can_import_and_list(client, admin):
    assert upload(client, admin, csv_bytes(line())).status_code == 201
    assert client.get("/api/v1/payments", headers=admin).json()["total"] == 1


# ------------------------------------------------------------------ listing / filtering


@pytest.fixture
def sample_payments(client, finance):
    upload(
        client, finance,
        csv_bytes(
            line("TXN-1", "INV-1", "Alpha Corp", "USD", "100.00", (TODAY - timedelta(days=10)).isoformat()),
            line("TXN-2", "INV-2", "Beta GmbH", "EUR", "250.00", (TODAY - timedelta(days=5)).isoformat()),
            line("TXN-3", "INV-3", "Alpha Corp", "GBP", "75.00", (TODAY - timedelta(days=1)).isoformat()),
            line("TXN-4", "", "Gamma LLC", "USD", "900.00", TODAY.isoformat()),
        ),
    )


def refs(resp) -> list[str]:
    return [p["transaction_reference"] for p in resp.json()["items"]]


def test_list_default_order_is_newest_first(client, finance, sample_payments):
    assert refs(client.get("/api/v1/payments", headers=finance)) == ["TXN-4", "TXN-3", "TXN-2", "TXN-1"]


def test_list_item_shape_and_money_strings(client, finance, sample_payments):
    item = client.get("/api/v1/payments", params={"search": "TXN-1"}, headers=finance).json()["items"][0]
    assert item["amount"] == "100.00" and item["allocated_amount"] == "0.00"
    assert item["status"] == "PENDING" and item["payment_reference"] == "INV-1"


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"currency": "USD"}, {"TXN-1", "TXN-4"}),
        ({"currency": "eur"}, {"TXN-2"}),
        ({"sender": "alpha"}, {"TXN-1", "TXN-3"}),
        ({"transaction_reference": "txn-2"}, {"TXN-2"}),
        ({"search": "gamma"}, {"TXN-4"}),
        ({"search": "INV-3"}, {"TXN-3"}),
        ({"status": "PENDING"}, {"TXN-1", "TXN-2", "TXN-3", "TXN-4"}),
        ({"status": "MATCHED"}, set()),
        ({"date_from": (TODAY - timedelta(days=5)).isoformat()}, {"TXN-2", "TXN-3", "TXN-4"}),
        ({"date_to": (TODAY - timedelta(days=5)).isoformat()}, {"TXN-1", "TXN-2"}),
        ({"currency": "USD", "sender": "gamma"}, {"TXN-4"}),
    ],
)
def test_list_filters(client, finance, sample_payments, params, expected):
    assert set(refs(client.get("/api/v1/payments", params=params, headers=finance))) == expected


def test_list_filter_by_import_batch(client, finance, sample_payments):
    other = upload(client, finance, csv_bytes(line("TXN-9"))).json()
    resp = client.get("/api/v1/payments", params={"import_batch_id": other["id"]}, headers=finance)
    assert refs(resp) == ["TXN-9"]


def test_list_pagination_and_sorting(client, finance, sample_payments):
    page = client.get("/api/v1/payments", params={"page": 2, "page_size": 3}, headers=finance).json()
    assert page["total"] == 4 and page["pages"] == 2 and len(page["items"]) == 1
    asc = client.get("/api/v1/payments", params={"sort_by": "amount", "sort_dir": "asc"}, headers=finance)
    assert refs(asc) == ["TXN-3", "TXN-1", "TXN-2", "TXN-4"]


def test_list_rejects_bad_params(client, finance):
    assert client.get("/api/v1/payments", params={"page_size": 500}, headers=finance).status_code == 422
    assert client.get("/api/v1/payments", params={"status": "NOPE"}, headers=finance).status_code == 422
    assert client.get("/api/v1/payments", params={"sort_by": "password"}, headers=finance).status_code == 422


def test_list_includes_allocated_amount(client, finance, db):
    exporter = Exporter(company_name="E", country="India")
    buyer = Buyer(buyer_name="B", country="USA")
    db.add_all([exporter, buyer])
    db.flush()
    invoice = Invoice(
        invoice_number="INV-9", exporter_id=exporter.id, buyer_id=buyer.id, invoice_date=TODAY, due_date=TODAY,
        currency="USD", total_amount=Decimal("500.00"),
    )
    db.add(invoice)
    db.flush()
    upload(client, finance, csv_bytes(line("TXN-A", amount="300.00")))
    payment = db.scalar(select(Payment))
    db.add(
        PaymentAllocation(
            payment_id=payment.id, invoice_id=invoice.id, allocated_amount=Decimal("120.00"),
            currency="USD", allocation_type=AllocationType.AUTO,
        )
    )
    db.commit()
    item = client.get("/api/v1/payments", headers=finance).json()["items"][0]
    assert item["allocated_amount"] == "120.00" and item["amount"] == "300.00"
    detail = client.get(f"/api/v1/payments/{payment.id}", headers=finance).json()
    assert detail["allocations"][0]["invoice_number"] == "INV-9"
    assert detail["import_file_name"] == "bank.csv" and detail["bank_reference"] == "B-1"


def test_payment_detail_404(client, finance):
    assert client.get(f"/api/v1/payments/{uuid.uuid4()}", headers=finance).status_code == 404
    assert client.get("/api/v1/payments/not-a-uuid", headers=finance).status_code == 422
