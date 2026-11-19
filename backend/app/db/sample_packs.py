"""Extra bank-statement CSVs for demos ("payment packs").

Each pack is a different story to tell during a demo. They are written to `sample_data/payment_packs/` and
regenerated on every seed, so the dates are always recent and the invoice numbers always agree with the
seeded invoices.

IMPORTANT: packs 01 and 02 both act on the same invoices, so import ONE of them per freshly seeded database
(reset with `python -m app.db.seed`). Packs 03 and 04 can be imported at any time. Transaction references
never collide with the seed data (TXN-1xxx) or with sample_data/payments.csv (TXN-2xxx).

Values are strings on purpose: pack 03 contains deliberately invalid rows.
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

HEADER = [
    "transaction_reference", "payment_reference", "sender_name", "currency", "amount",
    "transaction_date", "bank_reference",
]

NORTHWIND = "Northwind Imports LLC"
ALPENROSE = "Alpenrose Handels GmbH"
THAMES = "Thames Gate Wholesale Ltd"
AL_NOOR = "Al Noor General Trading LLC"
LUMIERE = "Lumière Distribution SAS"
CALEDONIA = "Caledonia Retail Group Ltd"
GULF_CREST = "Gulf Crest Foods FZE"
HARBOR = "Harbor & Pine Trading Co"
DELTA = "Delta Retail Partners GmbH"

Row = tuple[str, str, str, str, str, int | str, str]  # ref, payment ref, sender, currency, amount, days ago | date, bank ref


def _bank(n: int) -> str:
    return f"SIM-SWIFT-{480000 + n}"


# --- Pack 01: a clean month-end. Every open or overdue invoice is settled exactly: ten MATCHED payments.
CLEAN_SETTLEMENTS: list[Row] = [
    ("TXN-3001", "INV-1013", AL_NOOR, "AED", "45000.00", 2, _bank(301)),
    ("TXN-3002", "INV-1014", LUMIERE, "EUR", "10200.00", 2, _bank(302)),
    ("TXN-3003", "INV-1015", CALEDONIA, "GBP", "9300.00", 2, _bank(303)),
    ("TXN-3004", "INV-1016", GULF_CREST, "AED", "32500.00", 1, _bank(304)),
    ("TXN-3005", "INV-1017", NORTHWIND, "USD", "22000.00", 1, _bank(305)),
    ("TXN-3006", "INV-1018", ALPENROSE, "EUR", "11000.00", 1, _bank(306)),
    ("TXN-3007", "INV-1020", AL_NOOR, "AED", "28000.00", 1, _bank(307)),
    ("TXN-3008", "INV-1021", THAMES, "GBP", "5200.00", 1, _bank(308)),
    ("TXN-3009", "INV-1022", LUMIERE, "EUR", "9900.00", 1, _bank(309)),
    ("TXN-3010", "INV-1024", HARBOR, "USD", "500.00", 1, _bank(310)),
]

# --- Pack 02: a messy bank day. One payment per kind of trouble the engine is built to handle.
MESSY_BANK_DAY: list[Row] = [
    ("TXN-4001", "INV-1013", AL_NOOR, "AED", "20000.00", 2, _bank(401)),  # partial: less than owed
    ("TXN-4002", "INV-1017", NORTHWIND, "USD", "10000.00", 2, _bank(402)),  # partial
    ("TXN-4003", "INV-1018", ALPENROSE, "EUR", "5000.00", 1, _bank(403)),  # partial
    ("TXN-4004", "INV-1022", LUMIERE, "EUR", "10500.00", 1, _bank(404)),  # overpayment -> manual review
    ("TXN-4005", "INV-1021", "Zenith Marine Exports Inc", "GBP", "5200.00", 1, _bank(405)),  # right reference, different payer
    ("TXN-4006", "INV-1020", AL_NOOR, "USD", "28000.00", 1, _bank(406)),  # wrong currency (invoice is AED)
    ("TXN-4007", "", AL_NOOR, "AED", "28000.00", 1, _bank(407)),  # no reference, name and amount look right
    ("TXN-4008", "inv-1014", LUMIERE, "EUR", "10200.00", 1, _bank(408)),  # reference in lower case
    ("TXN-4009", "INV-1015", "Caledonia Retail Group Limited", "GBP", "9300.00", 1, _bank(409)),  # name spelled differently
    ("TXN-4010", "INV-1016", GULF_CREST, "AED", "32500.00", 3, _bank(410)),  # exact: will be a full match
    ("TXN-4011", "INV-1016", GULF_CREST, "AED", "32500.00", 3, _bank(411)),  # same payment again under a new reference
    ("TXN-4012", "INV-1010", NORTHWIND, "USD", "12500.00", 1, _bank(412)),  # pays an invoice that is already paid
    ("TXN-4013", "INV-1023", NORTHWIND, "USD", "3400.00", 1, _bank(413)),  # pays an invoice that is still a draft
    ("TXN-4014", "INV-9876", "Meridian Overseas Ltd", "USD", "6400.00", 2, _bank(414)),  # reference matches nothing
    ("TXN-4015", "PO-55102", HARBOR, "USD", "4100.00", 2, _bank(415)),  # a purchase-order number, not an invoice
    ("TXN-4016", "INV-1024", HARBOR, "USD", "500.00", 1, _bank(416)),  # settles the last 500 of INV-1024
]

# --- Pack 03: a bad file. Every row fails a different validation rule, plus three good rows.
VALIDATION_ERRORS: list[Row] = [
    ("TXN-5001", "INV-1017", NORTHWIND, "USD", "-500.00", 1, _bank(501)),  # negative amount
    ("TXN-5002", "INV-1017", NORTHWIND, "USD", "0", 1, _bank(502)),  # zero amount
    ("TXN-5003", "INV-1017", NORTHWIND, "USD", "1500.505", 1, _bank(503)),  # three decimals
    ("TXN-5004", "INV-1017", NORTHWIND, "USD", "1,500.00", 1, _bank(504)),  # comma in the amount
    ("TXN-5005", "INV-1017", NORTHWIND, "USD", "$1500", 1, _bank(505)),  # currency symbol in the amount
    ("", "INV-1017", NORTHWIND, "USD", "1500.00", 1, _bank(506)),  # missing transaction reference
    ("TXN-5007", "INV-1017", NORTHWIND, "", "1500.00", 1, _bank(507)),  # missing currency
    ("TXN-5008", "INV-1017", NORTHWIND, "US", "1500.00", 1, _bank(508)),  # currency is not three letters
    ("TXN-5009", "INV-1017", NORTHWIND, "USD", "1500.00", "15/11/2026", _bank(509)),  # wrong date format
    ("TXN-5010", "INV-1017", NORTHWIND, "USD", "1500.00", "2031-01-01", _bank(510)),  # date in the future
    ("TXN-5011", "INV-1017", "", "USD", "1500.00", 1, _bank(511)),  # missing sender
    ("TXN-5012", "INV-1017", "N" * 300, "USD", "1500.00", 1, _bank(512)),  # sender name far too long
    ("TXN-5013", "INV-1017", NORTHWIND, "USD", "1500.00", 1, _bank(513)),  # GOOD
    ("TXN-5013", "INV-1017", NORTHWIND, "USD", "1500.00", 1, _bank(513)),  # same transaction twice in one file
    ("TXN-5014", "INV-1018", ALPENROSE, "EUR", "2000.00", 1, _bank(514)),  # GOOD
    ("TXN-5015", "INV-1021", THAMES, "GBP", "1000.00", 1, _bank(515)),  # GOOD
]

_REMITTERS = [
    "Orchid Bay Traders", "Sunridge Wholesale Co", "Kestrel Logistics Ltd", "Baltic Pine Imports",
    "Maple Harbour Trading", "Desert Rose Commerce LLC", "Silverline Foods GmbH", "Redwood Supply Co",
    "Nordlicht Handel AG", "Coral Reef Exports", "Highland Textiles Ltd", "Atlas Peak Trading",
    "Willow Creek Imports", "Granite Bay Distributors", "Lotus Garden Foods", "Ironbridge Metals Ltd",
]
_CURRENCIES = [("USD", 0.4), ("EUR", 0.25), ("GBP", 0.15), ("AED", 0.2)]


def high_volume(count: int = 60) -> list[Row]:
    """Pack 04: many unrelated receipts across about 90 days, so trends and charts have something to show.

    Deterministic (fixed seed): the same file every time. None reference an invoice, so they all land as
    UNMATCHED; this pack is about volume, not matching.
    """
    rng = random.Random(2026)
    rows: list[Row] = []
    for n in range(count):
        currency = rng.choices([c for c, _ in _CURRENCIES], weights=[w for _, w in _CURRENCIES])[0]
        amount = rng.randrange(8, 400) * 125 + rng.choice([0, 0, 0, 50, 75])
        reference = rng.choice(["", "", f"ADV-{rng.randrange(100, 999)}", f"PO-{rng.randrange(10000, 99999)}"])
        rows.append(
            (f"TXN-6{n + 1:03d}", reference, rng.choice(_REMITTERS), currency, f"{amount}.00",
             rng.randrange(1, 90), _bank(600 + n))
        )
    return rows


PACKS: dict[str, list[Row]] = {
    "01_clean_month_end.csv": CLEAN_SETTLEMENTS,
    "02_messy_bank_day.csv": MESSY_BANK_DAY,
    "03_validation_errors.csv": VALIDATION_ERRORS,
    "04_high_volume.csv": high_volume(),
}


def write_payment_packs(today: date | None = None, out_dir: Path | None = None) -> list[Path]:
    from app.db.seed import SAMPLE_DATA_DIR

    today = today or date.today()
    target = (out_dir or SAMPLE_DATA_DIR) / "payment_packs"
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, rows in PACKS.items():
        path = target / name
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(HEADER)
            for ref, pay, sender, cur, amt, ago, bank in rows:
                tx_date = ago if isinstance(ago, str) else (today - timedelta(days=ago)).isoformat()
                writer.writerow([ref, pay, sender, cur, amt, tx_date, bank])
        written.append(path)
    return written
