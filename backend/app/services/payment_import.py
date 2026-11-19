"""Pure CSV parsing and row validation for bank payment imports (BRD FR-010 / FR-011).

No database or HTTP code lives here, so every rule is unit-testable. Money is parsed straight from
text into `Decimal`; floats are never involved.
"""

import csv
import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.core.constants import SUPPORTED_CURRENCIES
from app.core.errors import BusinessValidationError

# Column order from the spec. The first five are mandatory; the last two may be absent or blank.
CSV_COLUMNS = (
    "transaction_reference",
    "payment_reference",
    "sender_name",
    "currency",
    "amount",
    "transaction_date",
    "bank_reference",
)
REQUIRED_COLUMNS = ("transaction_reference", "sender_name", "currency", "amount", "transaction_date")

MAX_REFERENCE_LEN = 100
MAX_NAME_LEN = 255

_AMOUNT_RE = re.compile(r"^\d{1,16}(\.\d{1,2})?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class ParsedRow:
    line: int  # 1-based line number in the file (header is line 1)
    raw: dict[str, str]


@dataclass(frozen=True)
class ValidRow:
    line: int
    transaction_reference: str
    payment_reference: str | None
    sender_name: str
    currency: str
    amount: Decimal
    transaction_date: date
    bank_reference: str | None


@dataclass(frozen=True)
class RowIssue:
    field: str
    message: str


def _normalise_header(name: str) -> str:
    return re.sub(r"\s+", "_", name.strip().lower())


def parse_csv(content: bytes, *, max_rows: int) -> list[ParsedRow]:
    """Decode and split the file into raw rows. Raises BusinessValidationError for unusable files."""
    if not content.strip():
        raise BusinessValidationError("The file is empty")
    try:
        text = content.decode("utf-8-sig")  # tolerates the BOM that Excel adds
    except UnicodeDecodeError as exc:
        raise BusinessValidationError("The file must be a UTF-8 encoded CSV") from exc
    if "\x00" in text:
        raise BusinessValidationError("The file does not look like a text CSV")

    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise BusinessValidationError("The file is empty") from exc
    except csv.Error as exc:
        raise BusinessValidationError("The file is not a valid CSV") from exc

    columns = [_normalise_header(h) for h in header]
    if len(columns) == 1 and (";" in header[0] or "\t" in header[0]):
        raise BusinessValidationError("The file must be comma-separated (found ';' or tab delimiters)")
    missing = [c for c in REQUIRED_COLUMNS if c not in columns]
    if missing:
        raise BusinessValidationError(f"Missing required column(s): {', '.join(missing)}")
    if len(set(columns)) != len(columns):
        raise BusinessValidationError("The header contains duplicate column names")

    rows: list[ParsedRow] = []
    try:
        for fields in reader:
            if not any(f.strip() for f in fields):
                continue  # skip blank lines
            if len(rows) >= max_rows:
                raise BusinessValidationError(f"Too many rows: a file can contain at most {max_rows} transactions")
            raw = {columns[i]: (fields[i] if i < len(fields) else "") for i in range(len(columns))}
            if len(fields) > len(columns):
                raw["__extra__"] = "1"  # flagged during validation
            rows.append(ParsedRow(line=reader.line_num, raw=raw))
    except csv.Error as exc:
        raise BusinessValidationError(f"The file is not a valid CSV (line {reader.line_num})") from exc
    return rows


def validate_row(row: ParsedRow, today: date) -> tuple[ValidRow | None, list[RowIssue]]:
    """Validate one raw row. Returns (valid_row, []) or (None, issues) with every problem found."""
    raw = row.raw
    issues: list[RowIssue] = []
    get = lambda key: raw.get(key, "").strip()  # noqa: E731

    if "__extra__" in raw:
        issues.append(RowIssue("row", "Row has more values than the header has columns"))

    txn_ref = get("transaction_reference")
    if not txn_ref:
        issues.append(RowIssue("transaction_reference", "Transaction reference is required"))
    elif len(txn_ref) > MAX_REFERENCE_LEN:
        issues.append(RowIssue("transaction_reference", f"Must be at most {MAX_REFERENCE_LEN} characters"))

    payment_ref = get("payment_reference") or None
    if payment_ref and len(payment_ref) > MAX_REFERENCE_LEN:
        issues.append(RowIssue("payment_reference", f"Must be at most {MAX_REFERENCE_LEN} characters"))

    bank_ref = get("bank_reference") or None
    if bank_ref and len(bank_ref) > MAX_REFERENCE_LEN:
        issues.append(RowIssue("bank_reference", f"Must be at most {MAX_REFERENCE_LEN} characters"))

    sender = get("sender_name")
    if not sender:
        issues.append(RowIssue("sender_name", "Sender name is required"))
    elif len(sender) > MAX_NAME_LEN:
        issues.append(RowIssue("sender_name", f"Must be at most {MAX_NAME_LEN} characters"))

    currency = get("currency").upper()
    if not currency:
        issues.append(RowIssue("currency", "Currency is required"))
    elif currency not in SUPPORTED_CURRENCIES:
        issues.append(RowIssue("currency", f"Unsupported currency '{currency}'. Supported: {', '.join(SUPPORTED_CURRENCIES)}"))

    amount: Decimal | None = None
    amount_text = get("amount")
    if not amount_text:
        issues.append(RowIssue("amount", "Amount is required"))
    elif not _AMOUNT_RE.match(amount_text):
        issues.append(
            RowIssue("amount", "Amount must be a plain number with at most 2 decimals (no commas or symbols)")
        )
    else:
        amount = Decimal(amount_text)
        if amount <= 0:
            issues.append(RowIssue("amount", "Amount must be greater than zero"))
            amount = None

    tx_date: date | None = None
    date_text = get("transaction_date")
    if not date_text:
        issues.append(RowIssue("transaction_date", "Transaction date is required"))
    elif not _DATE_RE.match(date_text):
        issues.append(RowIssue("transaction_date", "Date must use the format YYYY-MM-DD"))
    else:
        try:
            tx_date = date.fromisoformat(date_text)
        except ValueError:
            issues.append(RowIssue("transaction_date", "Not a real calendar date"))
        else:
            if tx_date > today:
                issues.append(RowIssue("transaction_date", "Transaction date cannot be in the future"))
                tx_date = None

    if issues or amount is None or tx_date is None:
        return None, issues

    return (
        ValidRow(
            line=row.line,
            transaction_reference=txn_ref,
            payment_reference=payment_ref,
            sender_name=sender,
            currency=currency,
            amount=amount,
            transaction_date=tx_date,
            bank_reference=bank_ref,
        ),
        [],
    )


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value: object) -> str:
    """Neutralise spreadsheet formula injection: Excel/Sheets execute cells that start with = + - @.

    The error report echoes user-supplied text, so any such cell is prefixed with an apostrophe.
    """
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text
