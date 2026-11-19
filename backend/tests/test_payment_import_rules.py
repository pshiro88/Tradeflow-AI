"""Unit tests for CSV parsing and row validation (no database involved)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.errors import BusinessValidationError
from app.services.payment_import import ParsedRow, parse_csv, sanitize_csv_cell, validate_row

TODAY = date(2026, 11, 16)
HEADER = "transaction_reference,payment_reference,sender_name,currency,amount,transaction_date,bank_reference"
GOOD = "TXN-1,INV-1,Acme LLC,USD,100.50,2026-11-10,BNK-1"


def parse(text: str, max_rows: int = 100) -> list[ParsedRow]:
    return parse_csv(text.encode("utf-8"), max_rows=max_rows)


def row(**overrides: str) -> ParsedRow:
    raw = {
        "transaction_reference": "TXN-1",
        "payment_reference": "INV-1",
        "sender_name": "Acme LLC",
        "currency": "USD",
        "amount": "100.50",
        "transaction_date": "2026-11-10",
        "bank_reference": "BNK-1",
    }
    raw.update(overrides)
    return ParsedRow(line=2, raw=raw)


# ------------------------------------------------------------------ parse_csv


def test_parse_valid_file_returns_rows_with_line_numbers():
    rows = parse(f"{HEADER}\n{GOOD}\nTXN-2,INV-2,Beta Ltd,EUR,5,2026-11-11,\n")
    assert [r.line for r in rows] == [2, 3]
    assert rows[0].raw["transaction_reference"] == "TXN-1"


def test_parse_tolerates_bom_header_case_and_spaces():
    text = "﻿Transaction Reference, Payment Reference ,Sender Name,CURRENCY,Amount,Transaction Date,Bank Reference\n" + GOOD
    rows = parse(text)
    assert rows[0].raw["sender_name"] == "Acme LLC"
    assert rows[0].raw["currency"] == "USD"


def test_parse_optional_columns_may_be_absent():
    rows = parse("transaction_reference,sender_name,currency,amount,transaction_date\nTXN-1,Acme,USD,10,2026-11-10")
    assert rows[0].raw.get("payment_reference") is None


def test_parse_ignores_unknown_extra_columns():
    rows = parse(f"{HEADER},notes\n{GOOD},hello")
    assert len(rows) == 1


def test_parse_skips_blank_lines():
    rows = parse(f"{HEADER}\n\n{GOOD}\n,,,,,,\n")
    assert len(rows) == 1


def test_parse_handles_quoted_commas():
    rows = parse(f'{HEADER}\nTXN-1,INV-1,"Smith, Jones Ltd",USD,10,2026-11-10,')
    assert rows[0].raw["sender_name"] == "Smith, Jones Ltd"


def test_parse_header_only_returns_no_rows():
    assert parse(HEADER + "\n") == []


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "empty"),
        (b"   \n  \n", "empty"),
        (b"transaction_reference,amount\nTXN-1,10", "Missing required column"),
        (b"transaction_reference;sender_name;currency;amount;transaction_date\nA;B;USD;1;2026-01-01", "comma-separated"),
        (b"\xff\xfe\x00bad", "UTF-8"),
        (f"{HEADER},Amount\n".encode(), "duplicate column"),
    ],
)
def test_parse_rejects_unusable_files(content, message):
    with pytest.raises(BusinessValidationError) as exc:
        parse_csv(content, max_rows=100)
    assert message.lower() in exc.value.message.lower()


def test_parse_enforces_row_limit():
    text = HEADER + "\n" + "\n".join(f"TXN-{i},INV,A,USD,1,2026-11-10," for i in range(6))
    assert len(parse(text, max_rows=6)) == 6
    with pytest.raises(BusinessValidationError, match="Too many rows"):
        parse(text, max_rows=5)


def test_parse_flags_rows_with_extra_values():
    rows = parse(f"{HEADER}\n{GOOD},surplus")
    valid, issues = validate_row(rows[0], TODAY)
    assert valid is None and issues[0].field == "row"


# ------------------------------------------------------------------ validate_row


def test_valid_row_is_parsed_into_exact_types():
    valid, issues = validate_row(row(), TODAY)
    assert issues == []
    assert valid is not None
    assert valid.amount == Decimal("100.50") and isinstance(valid.amount, Decimal)
    assert valid.transaction_date == date(2026, 11, 10)
    assert valid.currency == "USD"


def test_whitespace_is_trimmed_and_currency_uppercased():
    valid, _ = validate_row(row(sender_name="  Acme LLC  ", currency=" usd ", transaction_reference=" TXN-9 "), TODAY)
    assert valid.sender_name == "Acme LLC" and valid.currency == "USD" and valid.transaction_reference == "TXN-9"


def test_blank_optional_fields_become_none():
    valid, _ = validate_row(row(payment_reference="  ", bank_reference=""), TODAY)
    assert valid.payment_reference is None and valid.bank_reference is None


@pytest.mark.parametrize("amount", ["10", "10.5", "10.50", "0.01", "9999999999999999.99"])
def test_valid_amounts(amount):
    valid, issues = validate_row(row(amount=amount), TODAY)
    assert issues == [] and valid.amount == Decimal(amount)


@pytest.mark.parametrize(
    "amount",
    ["", "abc", "0", "0.00", "-5", "+5", "1,000.00", "$100", "1e3", "10.123", "NaN", "Infinity", "1.", ".5", "12 34"],
)
def test_invalid_amounts_are_rejected(amount):
    valid, issues = validate_row(row(amount=amount), TODAY)
    assert valid is None
    assert [i.field for i in issues] == ["amount"]


@pytest.mark.parametrize("value", ["", "31-13-2026", "2026/11/10", "10-11-2026", "20261110", "2026-13-01", "2026-02-30", "yesterday"])
def test_invalid_dates_are_rejected(value):
    valid, issues = validate_row(row(transaction_date=value), TODAY)
    assert valid is None and [i.field for i in issues] == ["transaction_date"]


def test_today_is_allowed_but_future_is_rejected():
    assert validate_row(row(transaction_date=TODAY.isoformat()), TODAY)[0] is not None
    valid, issues = validate_row(row(transaction_date=(TODAY + timedelta(days=1)).isoformat()), TODAY)
    assert valid is None and "future" in issues[0].message


@pytest.mark.parametrize("currency", ["XYZ", "JPY", "US", "", "DOLLAR"])
def test_unsupported_currency_is_rejected(currency):
    valid, issues = validate_row(row(currency=currency), TODAY)
    assert valid is None and [i.field for i in issues] == ["currency"]


@pytest.mark.parametrize("currency", ["USD", "EUR", "GBP", "AED", "INR"])
def test_supported_currencies_are_accepted(currency):
    assert validate_row(row(currency=currency), TODAY)[0] is not None


def test_required_text_fields():
    for field in ("transaction_reference", "sender_name"):
        valid, issues = validate_row(row(**{field: "  "}), TODAY)
        assert valid is None and issues[0].field == field


def test_overlong_values_are_rejected():
    assert validate_row(row(transaction_reference="X" * 101), TODAY)[0] is None
    assert validate_row(row(sender_name="X" * 256), TODAY)[0] is None
    assert validate_row(row(payment_reference="X" * 101), TODAY)[0] is None
    assert validate_row(row(transaction_reference="X" * 100), TODAY)[0] is not None


def test_all_problems_in_a_row_are_reported_together():
    valid, issues = validate_row(row(currency="XYZ", amount="abc", sender_name="", transaction_date="bad"), TODAY)
    assert valid is None
    assert {i.field for i in issues} == {"currency", "amount", "sender_name", "transaction_date"}


# ------------------------------------------------------------------ sanitize_csv_cell


@pytest.mark.parametrize("value", ["=1+1", "+cmd", "-2+3", "@SUM(A1)", "\tcmd", '=HYPERLINK("http://evil","x")'])
def test_formula_cells_are_neutralised(value):
    assert sanitize_csv_cell(value).startswith("'")


@pytest.mark.parametrize("value", ["Acme LLC", "TXN-1", "100.50", "", None])
def test_normal_cells_are_untouched(value):
    assert sanitize_csv_cell(value) == ("" if value is None else value)
