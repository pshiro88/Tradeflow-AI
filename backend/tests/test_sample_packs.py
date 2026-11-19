"""The demo payment packs (sample_data/payment_packs) must keep telling the story they claim to tell.

If the seed data changes (invoice numbers, amounts, currencies), these tests fail and say which pack drifted.
"""

import pytest

from app.db.sample_packs import PACKS, write_payment_packs
from app.db.seed import seed_demo_data

IMPORT = "/api/v1/payments/import"
RECON = "/api/v1/reconciliation"


@pytest.fixture
def packs(tmp_path):
    write_payment_packs(out_dir=tmp_path)
    return tmp_path / "payment_packs"


@pytest.fixture
def seeded(db, client, finance):
    seed_demo_data(db)
    db.commit()
    # The seed leaves payments PENDING; reconcile them like `python -m app.db.seed` does.
    assert client.post(f"{RECON}/run", headers=finance).status_code == 200


def import_pack(client, headers, packs, name):
    resp = client.post(IMPORT, files={"file": (name, (packs / name).read_bytes(), "text/csv")}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def outcomes(client, headers, prefix):
    items = client.get(RECON, params={"page_size": 100}, headers=headers).json()["items"]
    return {i["transaction_reference"]: i["status"] for i in items if i["transaction_reference"].startswith(prefix)}


def test_every_pack_is_written_and_has_unique_transaction_references(packs):
    assert sorted(p.name for p in packs.iterdir()) == sorted(PACKS)
    seen: dict[str, str] = {}
    for name, rows in PACKS.items():
        for row in rows:
            ref = row[0]
            if ref and name != "03_validation_errors.csv":  # pack 03 repeats a reference on purpose
                assert ref not in seen, f"{ref} appears in {name} and {seen[ref]}"
                seen[ref] = name
                assert not ref.startswith(("TXN-1", "TXN-2")), "would collide with the seed data or payments.csv"


def test_clean_month_end_settles_every_open_invoice(client, finance, packs, seeded):
    batch = import_pack(client, finance, packs, "01_clean_month_end.csv")
    assert (batch["accepted_rows"], batch["rejected_rows"], batch["duplicate_rows"]) == (10, 0, 0)
    assert set(outcomes_after_run(client, finance, "TXN-3").values()) == {"MATCHED"}
    invoices = client.get("/api/v1/invoices", params={"page_size": 100}, headers=finance).json()["items"]
    status = {i["invoice_number"]: i["status"] for i in invoices}
    assert [n for n, s in status.items() if s not in ("PAID", "DRAFT")] == []  # everything but the draft is paid


def outcomes_after_run(client, headers, prefix):
    assert client.post(f"{RECON}/run", headers=headers).status_code == 200
    return outcomes(client, headers, prefix)


def test_messy_bank_day_covers_every_outcome(client, finance, packs, seeded):
    batch = import_pack(client, finance, packs, "02_messy_bank_day.csv")
    assert batch["accepted_rows"] == 16
    result = outcomes_after_run(client, finance, "TXN-4")
    assert set(result.values()) == {"MATCHED", "PARTIAL", "MANUAL_REVIEW", "MISMATCH", "DUPLICATE", "UNMATCHED"}
    assert result["TXN-4011"] == "DUPLICATE"  # the bank sent TXN-4010 twice
    assert result["TXN-4004"] == "MANUAL_REVIEW"  # overpayment is never allocated automatically
    assert result["TXN-4006"] == "MISMATCH"  # wrong currency
    assert result["TXN-4013"] == "MISMATCH"  # draft invoice cannot receive money


def test_validation_pack_shows_each_rule_and_keeps_three_good_rows(client, finance, packs, seeded):
    batch = import_pack(client, finance, packs, "03_validation_errors.csv")
    assert (batch["accepted_rows"], batch["rejected_rows"], batch["duplicate_rows"]) == (3, 12, 1)


def test_high_volume_pack_imports_all_rows_and_none_match(client, finance, packs, seeded):
    batch = import_pack(client, finance, packs, "04_high_volume.csv")
    assert batch["accepted_rows"] == 60
    result = outcomes_after_run(client, finance, "TXN-6")
    assert len(result) == 60 and set(result.values()) == {"UNMATCHED"}
