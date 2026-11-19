"""Dashboard tests.

The expected figures were derived BY HAND from the seed data in app/db/seed_data.py (see the scenario map
there), independent of the code under test, so they act as an oracle rather than a copy of the queries.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.seed import seed_demo_data
from app.models.party import Buyer
from app.services.dashboard_service import _add_months, _last_of_month

URL = "/api/v1/dashboard"
TODAY = date.today()
D = Decimal

ENDPOINTS = [
    "summary", "payment-trends", "payment-distribution", "currency-distribution", "recent-transactions", "outstanding-invoices",
]


@pytest.fixture
def reconciled(client, finance, db):
    """Demo data after a reconciliation run (the state `python -m app.db.seed` leaves behind)."""
    seed_demo_data(db)
    db.commit()
    assert client.post("/api/v1/reconciliation/run", headers=finance).status_code == 200


def get(client, headers, endpoint, **params):
    return client.get(f"{URL}/{endpoint}", params=params, headers=headers)


def money(items) -> dict[str, str]:
    return {i["currency"]: i["amount"] for i in items}


def buyer_id(db, name: str) -> str:
    return str(db.scalar(select(Buyer.id).where(Buyer.buyer_name == name)))


# ===================================================================== summary: hand-computed figures


def test_summary_matches_hand_computed_figures(client, finance, reconciled):
    s = get(client, finance, "summary").json()
    # 14 issued invoices (INV-1023 is a draft), values per currency
    assert s["total_invoices"] == 14
    assert money(s["total_invoice_value"]) == {"USD": "52300.00", "EUR": "44500.00", "GBP": "21250.00", "AED": "135500.00"}
    # bank receipts per currency, duplicates (TXN-1010, TXN-1011) excluded
    assert money(s["payments_received"]) == {"USD": "62799.99", "EUR": "45300.00", "GBP": "24150.00", "AED": "45000.00"}
    # received but not applied to any invoice
    assert money(s["unallocated_received"]) == {"USD": "32999.99", "EUR": "31900.00", "GBP": "17400.00", "AED": "15000.00"}
    # outstanding balance on issued invoices
    assert money(s["pending_amount"]) == {"USD": "22500.00", "EUR": "31100.00", "GBP": "14500.00", "AED": "105500.00"}
    assert s["fully_reconciled_invoices"] == 4  # INV-1010, 1011, 1012, 1019
    assert s["partially_paid_invoices"] == 3  # INV-1024, 1014, 1016 (two of them are also overdue)
    assert s["unmatched_transactions"] == 5  # TXN-1012 .. TXN-1016
    assert s["overdue_invoices"] == 5  # INV-1013, 1014, 1015, 1016, 1020


def test_currencies_are_listed_in_a_stable_order_and_never_summed(client, finance, reconciled):
    s = get(client, finance, "summary").json()
    assert [i["currency"] for i in s["total_invoice_value"]] == ["USD", "EUR", "GBP", "AED"]
    assert len(s["total_invoice_value"]) == 4  # one line per currency, no grand total


def test_summary_amounts_are_decimal_strings(client, finance, reconciled):
    s = get(client, finance, "summary").json()
    assert all(isinstance(i["amount"], str) for i in s["payments_received"])


def test_empty_database_gives_zeroes_not_errors(client, finance):
    s = get(client, finance, "summary").json()
    assert s["total_invoices"] == 0 and s["total_invoice_value"] == [] and s["pending_amount"] == []
    assert s["overdue_invoices"] == s["unmatched_transactions"] == 0
    assert get(client, finance, "payment-distribution").json()["total"] == 0
    assert get(client, finance, "currency-distribution").json()["items"] == []
    assert get(client, finance, "recent-transactions").json() == []
    assert get(client, finance, "outstanding-invoices").json() == []
    trends = get(client, finance, "payment-trends").json()
    assert trends["currency"] == "USD" and len(trends["points"]) == 6
    assert all(p["invoiced"] == "0.00" and p["received"] == "0.00" for p in trends["points"])


def test_dashboard_agrees_with_the_invoices_page(client, finance, reconciled):
    """Guards against the dashboard and invoice list drifting apart on what is paid / overdue."""
    s = get(client, finance, "summary").json()
    invoices = "/api/v1/invoices"
    assert client.get(invoices, params={"status": "OVERDUE"}, headers=finance).json()["total"] == s["overdue_invoices"]
    assert client.get(invoices, params={"status": "PAID"}, headers=finance).json()["total"] == s["fully_reconciled_invoices"]
    assert client.get(invoices, params={"page_size": 100}, headers=finance).json()["total"] - 1 == s["total_invoices"]  # minus the draft


def test_dashboard_reflects_manual_review_decisions(client, finance, reconciled, db):
    before = get(client, finance, "summary").json()
    results = client.get("/api/v1/reconciliation", params={"search": "TXN-1019"}, headers=finance).json()["items"]
    invoice_id = results[0]["invoice_id"]
    client.post(f"/api/v1/reconciliation/{results[0]['id']}/approve", json={"invoice_id": invoice_id}, headers=finance)
    after = get(client, finance, "summary").json()
    assert after["fully_reconciled_invoices"] == before["fully_reconciled_invoices"] + 1  # INV-1021 is now paid
    assert money(after["unallocated_received"])["GBP"] == "12200.00"  # 17,400 - 5,200 applied
    assert money(after["pending_amount"])["GBP"] == "9300.00"  # 14,500 - 5,200


# ===================================================================== summary: filters


def test_currency_filter(client, finance, reconciled):
    s = get(client, finance, "summary", currency="USD").json()
    assert s["total_invoices"] == 4  # INV-1010, 1017, 1019, 1024
    assert money(s["total_invoice_value"]) == {"USD": "52300.00"}
    assert money(s["payments_received"]) == {"USD": "62799.99"}
    assert s["fully_reconciled_invoices"] == 2 and s["partially_paid_invoices"] == 1 and s["overdue_invoices"] == 0
    assert s["unmatched_transactions"] == 3  # TXN-1012, 1013, 1016
    assert money(get(client, finance, "summary", currency="aed").json()["pending_amount"]) == {"AED": "105500.00"}


def test_unknown_currency_returns_empty_results(client, finance, reconciled):
    s = get(client, finance, "summary", currency="JPY").json()
    assert s["total_invoices"] == 0 and s["payments_received"] == []


def test_date_ranges_partition_the_data(client, finance, reconciled):
    """Two complementary date ranges must add up to the unfiltered totals."""
    cut = TODAY - timedelta(days=30)
    recent = get(client, finance, "summary", date_from=cut.isoformat()).json()
    older = get(client, finance, "summary", date_to=(cut - timedelta(days=1)).isoformat()).json()
    assert recent["total_invoices"] == 7 and older["total_invoices"] == 7
    for currency, total in {"USD": "52300.00", "EUR": "44500.00", "GBP": "21250.00", "AED": "135500.00"}.items():
        parts = D(money(recent["total_invoice_value"]).get(currency, "0")) + D(money(older["total_invoice_value"]).get(currency, "0"))
        assert parts == D(total)

    cut = TODAY - timedelta(days=10)
    newer = get(client, finance, "summary", date_from=cut.isoformat(), currency="USD").json()
    earlier = get(client, finance, "summary", date_to=(cut - timedelta(days=1)).isoformat(), currency="USD").json()
    received = D(money(newer["payments_received"]).get("USD", "0")) + D(money(earlier["payments_received"]).get("USD", "0"))
    assert received == D("62799.99")


def test_payment_status_filter_narrows_payment_metrics_only(client, finance, reconciled):
    s = get(client, finance, "summary", status="UNMATCHED").json()
    assert money(s["payments_received"]) == {"USD": "21999.99", "GBP": "2100.00", "AED": "15000.00"}
    assert s["unmatched_transactions"] == 5
    assert s["total_invoices"] == 14 and money(s["pending_amount"])["AED"] == "105500.00"  # invoice metrics untouched
    assert get(client, finance, "summary", status="MATCHED").json()["unmatched_transactions"] == 0


def test_buyer_filter(client, finance, reconciled, db):
    s = get(client, finance, "summary", buyer_id=buyer_id(db, "Harbor & Pine Trading Co")).json()
    assert s["total_invoices"] == 2  # INV-1019 (paid) and INV-1024 (500 outstanding)
    assert money(s["total_invoice_value"]) == {"USD": "17800.00"}
    assert money(s["pending_amount"]) == {"USD": "500.00"}
    assert money(s["payments_received"]) == {"USD": "17300.00"}  # TXN-1004, 1005, 1020: the ones applied to this buyer
    assert s["fully_reconciled_invoices"] == 1 and s["partially_paid_invoices"] == 1 and s["overdue_invoices"] == 0
    assert s["unmatched_transactions"] == 0  # unmatched payments belong to no buyer


def test_filters_can_be_combined(client, finance, reconciled, db):
    s = get(client, finance, "summary", buyer_id=buyer_id(db, "Harbor & Pine Trading Co"), currency="EUR").json()
    assert s["total_invoices"] == 0 and s["payments_received"] == []


@pytest.mark.parametrize(
    "params",
    [{"status": "NOPE"}, {"buyer_id": "not-a-uuid"}, {"date_from": "2026-13-01"}, {"date_from": "2026-05-02", "date_to": "2026-05-01"}],
)
def test_invalid_filters_return_422(client, finance, params):
    assert get(client, finance, "summary", **params).status_code == 422


# ===================================================================== trends


def test_trends_default_is_six_months_in_the_main_currency(client, finance, reconciled):
    t = get(client, finance, "payment-trends").json()
    assert t["currency"] == "USD"  # USD and EUR tie on invoice count; USD comes first
    assert t["available_currencies"] == ["USD", "EUR", "GBP", "AED"]
    months = [p["month"] for p in t["points"]]
    assert len(months) == 6 and months == sorted(months) and months[-1] == TODAY.strftime("%Y-%m")
    assert sum(D(p["invoiced"]) for p in t["points"]) == D("52300.00")
    assert sum(D(p["received"]) for p in t["points"]) == D("62799.99")


def test_trends_for_other_currencies_exclude_duplicates(client, finance, reconciled):
    gbp = get(client, finance, "payment-trends", currency="GBP").json()
    assert gbp["currency"] == "GBP"
    assert sum(D(p["invoiced"]) for p in gbp["points"]) == D("21250.00")
    assert sum(D(p["received"]) for p in gbp["points"]) == D("24150.00")  # TXN-1011 (duplicate) not counted
    eur = get(client, finance, "payment-trends", currency="eur").json()
    assert sum(D(p["invoiced"]) for p in eur["points"]) == D("44500.00")


def test_trends_always_offer_every_currency_even_when_one_is_chosen(client, finance, reconciled):
    """Regression: choosing EUR must not shrink the list of currencies you can switch to."""
    for chosen in ("USD", "EUR", "AED"):
        t = get(client, finance, "payment-trends", currency=chosen).json()
        assert t["currency"] == chosen
        assert t["available_currencies"] == ["USD", "EUR", "GBP", "AED"]


def test_trends_months_without_activity_are_zero_filled(client, finance, reconciled):
    points = get(client, finance, "payment-trends", months=12).json()["points"]
    assert len(points) == 12
    assert any(p["invoiced"] == "0.00" and p["received"] == "0.00" for p in points)
    assert len({p["month"] for p in points}) == 12


def test_trends_range_and_limits(client, finance, reconciled):
    assert len(get(client, finance, "payment-trends", months=1).json()["points"]) == 1
    assert get(client, finance, "payment-trends", months=0).status_code == 422
    assert get(client, finance, "payment-trends", months=25).status_code == 422
    # an explicit range wins over `months`, and is capped at 24 months
    wide = get(client, finance, "payment-trends", date_from=(TODAY - timedelta(days=365 * 6)).isoformat()).json()["points"]
    assert len(wide) == 24
    narrow = get(client, finance, "payment-trends", date_from=(TODAY - timedelta(days=40)).isoformat()).json()["points"]
    assert 2 <= len(narrow) <= 3


def test_trends_respect_the_date_filter(client, finance, reconciled):
    since = TODAY - timedelta(days=30)
    t = get(client, finance, "payment-trends", currency="USD", date_from=since.isoformat()).json()
    # USD invoices dated within the last 30 days: INV-1017 22,000 + INV-1019 7,800 + INV-1024 10,000
    assert sum(D(p["invoiced"]) for p in t["points"]) == D("39800.00")


def test_trends_reject_unsupported_currency(client, finance, reconciled):
    assert get(client, finance, "payment-trends", currency="JPY").status_code == 422


def test_month_arithmetic():
    assert _add_months(date(2026, 11, 1), 1) == date(2026, 12, 1)
    assert _add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)
    assert _add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)
    assert _add_months(date(2026, 3, 1), -5) == date(2025, 10, 1)
    assert _add_months(date(2026, 6, 1), 24) == date(2028, 6, 1)
    assert _last_of_month(date(2026, 2, 10)) == date(2026, 2, 28)
    assert _last_of_month(date(2028, 2, 10)) == date(2028, 2, 29)
    assert _last_of_month(date(2026, 12, 31)) == date(2026, 12, 31)


# ===================================================================== distributions


def test_payment_status_distribution(client, finance, reconciled):
    d = get(client, finance, "payment-distribution").json()
    counts = {i["status"]: i["count"] for i in d["items"]}
    assert counts == {
        "PENDING": 0, "MATCHED": 4, "PARTIAL": 4, "UNMATCHED": 5, "MISMATCH": 3, "DUPLICATE": 2, "MANUAL_REVIEW": 2,
    }
    assert d["total"] == 20


def test_status_distribution_ignores_the_status_filter_but_honours_others(client, finance, reconciled):
    assert get(client, finance, "payment-distribution", status="MATCHED").json()["total"] == 20
    usd = get(client, finance, "payment-distribution", currency="USD").json()
    assert usd["total"] == 9  # TXN-1001, 04, 05, 09, 10, 12, 13, 16, 20


def test_currency_distribution(client, finance, reconciled):
    items = {i["currency"]: i for i in get(client, finance, "currency-distribution").json()["items"]}
    assert list(items) == ["USD", "EUR", "GBP", "AED"]
    usd = items["USD"]
    assert (usd["invoices"], usd["payments"]) == (4, 8)  # 8 non-duplicate USD payments
    assert usd["invoice_value"] == "52300.00" and usd["received"] == "62799.99"
    assert (items["AED"]["invoices"], items["AED"]["payments"]) == (3, 2)
    assert items["GBP"]["received"] == "24150.00"


# ===================================================================== widgets


def test_recent_transactions_newest_first_with_applied_invoice_only(client, finance, reconciled):
    items = get(client, finance, "recent-transactions").json()
    assert len(items) == 8
    dates = [i["transaction_date"] for i in items]
    assert dates == sorted(dates, reverse=True)
    assert items[0]["transaction_reference"] == "TXN-1016"  # the most recent payment
    by_ref = {i["transaction_reference"]: i for i in get(client, finance, "recent-transactions", limit=50).json()}
    assert by_ref["TXN-1005"]["invoice_number"] == "INV-1024" and by_ref["TXN-1005"]["buyer_name"] == "Harbor & Pine Trading Co"
    # a MISMATCH has a candidate invoice but nothing was applied, so no invoice or buyer is shown
    assert by_ref["TXN-1008"]["invoice_number"] is None and by_ref["TXN-1008"]["buyer_name"] is None
    assert by_ref["TXN-1012"]["invoice_number"] is None  # unmatched
    assert len(by_ref) == 20


def test_recent_transactions_limit_and_filters(client, finance, reconciled):
    assert len(get(client, finance, "recent-transactions", limit=3).json()) == 3
    assert get(client, finance, "recent-transactions", limit=0).status_code == 422
    assert get(client, finance, "recent-transactions", limit=51).status_code == 422
    aed = get(client, finance, "recent-transactions", currency="AED", limit=50).json()
    assert {i["transaction_reference"] for i in aed} == {"TXN-1007", "TXN-1014"}
    unmatched = get(client, finance, "recent-transactions", status="UNMATCHED", limit=50).json()
    assert len(unmatched) == 5


def test_outstanding_invoices_oldest_due_first(client, finance, reconciled):
    items = get(client, finance, "outstanding-invoices", limit=5).json()
    assert [i["invoice_number"] for i in items] == ["INV-1020", "INV-1015", "INV-1014", "INV-1016", "INV-1013"]
    first = items[0]
    assert first["status"] == "OVERDUE" and first["days_overdue"] == 70 and first["outstanding_amount"] == "28000.00"
    by_number = {i["invoice_number"]: i for i in items}
    assert by_number["INV-1014"]["outstanding_amount"] == "10200.00"  # 15,200 less the 5,000 received
    assert by_number["INV-1016"]["outstanding_amount"] == "32500.00"


def test_outstanding_invoices_exclude_paid_and_draft_and_include_future_due(client, finance, reconciled):
    numbers = {i["invoice_number"] for i in get(client, finance, "outstanding-invoices", limit=50).json()}
    assert numbers.isdisjoint({"INV-1010", "INV-1011", "INV-1012", "INV-1019", "INV-1023"})  # paid or draft
    assert {"INV-1013", "INV-1024", "INV-1021"} <= numbers
    upcoming = [i for i in get(client, finance, "outstanding-invoices", limit=50).json() if i["invoice_number"] == "INV-1021"][0]
    assert upcoming["days_overdue"] < 0 and upcoming["status"] == "OPEN"  # negative = days until due


def test_outstanding_invoices_filters(client, finance, reconciled):
    gbp = get(client, finance, "outstanding-invoices", currency="GBP", limit=50).json()
    assert {i["invoice_number"] for i in gbp} == {"INV-1015", "INV-1021"}


# ===================================================================== authorization


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_unauthenticated_requests_return_401(client, endpoint):
    assert client.get(f"{URL}/{endpoint}").status_code == 401


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_operations_is_forbidden(client, ops, endpoint):
    assert get(client, ops, endpoint).status_code == 403


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_finance_and_admin_are_allowed(client, finance, admin, endpoint):
    assert get(client, finance, endpoint).status_code == 200
    assert get(client, admin, endpoint).status_code == 200


def test_unknown_buyer_id_is_just_empty(client, finance, reconciled):
    s = get(client, finance, "summary", buyer_id=str(uuid.uuid4())).json()
    assert s["total_invoices"] == 0 and s["payments_received"] == []
