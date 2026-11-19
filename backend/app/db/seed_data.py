"""Synthetic demo dataset (all names, companies and amounts are fictional).

Dates are expressed as "days ago" so the data always looks current: the 5 overdue invoices stay
overdue and the open ones stay open no matter when the database is reseeded.

Scenario map (what reconciliation should conclude once the engine exists, Step 6):

  MATCHED (full)     TXN-1001 -> INV-1010, TXN-1002 -> INV-1011, TXN-1003 -> INV-1012, TXN-1020 -> INV-1019
  PARTIAL            TXN-1004 + TXN-1005 -> INV-1024 (6,000 + 3,500 of 10,000), TXN-1006 -> INV-1014,
                     TXN-1007 -> INV-1016
  CURRENCY MISMATCH  TXN-1008 (EUR) vs INV-1017 (USD), TXN-1009 (USD) vs INV-1018 (EUR)
  DUPLICATE          TXN-1010 repeats TXN-1001, TXN-1011 repeats TXN-1003 (bank sent twice, new refs)
  UNMATCHED (5)      TXN-1012 .. TXN-1016
  MISMATCH (name)    TXN-1017 -> INV-1022 reference matches but the sender is a different company
  MANUAL_REVIEW      TXN-1018 (no reference, name + amount resemble INV-1015)
  OVERPAYMENT        TXN-1019 (6,000 paid against INV-1021 of 5,200)
  OVERDUE (5)        INV-1013, INV-1014, INV-1015, INV-1016, INV-1020
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ExporterSeed:
    company_name: str
    country: str
    email: str


@dataclass(frozen=True)
class BuyerSeed:
    buyer_name: str
    country: str
    email: str


@dataclass(frozen=True)
class InvoiceSeed:
    invoice_number: str
    exporter: str  # exporter company_name
    buyer: str  # buyer_name
    invoice_days_ago: int
    terms_days: int
    currency: str
    amount: Decimal
    description: str
    draft: bool = False

    @property
    def payment_terms(self) -> str:
        return f"Net {self.terms_days}"


@dataclass(frozen=True)
class PaymentSeed:
    transaction_reference: str
    payment_reference: str | None
    sender_name: str
    currency: str
    amount: Decimal
    days_ago: int
    bank_reference: str


EXPORTERS: list[ExporterSeed] = [
    ExporterSeed("Kaveri Textiles Pvt Ltd", "India", "accounts@kaveritextiles.example.com"),
    ExporterSeed("Sahyadri Spices & Foods Pvt Ltd", "India", "finance@sahyadrispices.example.com"),
    ExporterSeed("Meridian Engineering Works Pvt Ltd", "India", "exports@meridianworks.example.com"),
]

BUYERS: list[BuyerSeed] = [
    BuyerSeed("Northwind Imports LLC", "USA", "ap@northwindimports.example.com"),
    BuyerSeed("Harbor & Pine Trading Co", "USA", "payables@harborpine.example.com"),
    BuyerSeed("Alpenrose Handels GmbH", "Germany", "buchhaltung@alpenrose.example.com"),
    BuyerSeed("Lumière Distribution SAS", "France", "compta@lumieredistribution.example.com"),
    BuyerSeed("Thames Gate Wholesale Ltd", "United Kingdom", "accounts@thamesgate.example.com"),
    BuyerSeed("Caledonia Retail Group Ltd", "United Kingdom", "finance@caledoniaretail.example.com"),
    BuyerSeed("Al Noor General Trading LLC", "United Arab Emirates", "accounts@alnoortrading.example.com"),
    BuyerSeed("Gulf Crest Foods FZE", "United Arab Emirates", "finance@gulfcrestfoods.example.com"),
]

_K, _S, _M = (e.company_name for e in EXPORTERS)
_NW, _HP, _AL, _LU, _TG, _CA, _AN, _GC = (b.buyer_name for b in BUYERS)

INVOICES: list[InvoiceSeed] = [
    InvoiceSeed("INV-1010", _K, _NW, 50, 30, "USD", Decimal("12500.00"), "Cotton bed linen sets, 1 x 40ft container"),
    InvoiceSeed("INV-1011", _S, _AL, 45, 30, "EUR", Decimal("8400.00"), "Turmeric and cumin, 1 x 20ft container"),
    InvoiceSeed("INV-1012", _K, _TG, 35, 30, "GBP", Decimal("6750.00"), "Handloom cotton throws, 320 cartons"),
    InvoiceSeed("INV-1013", _M, _AN, 30, 15, "AED", Decimal("45000.00"), "CNC machined auto components, 12 pallets"),
    InvoiceSeed("INV-1014", _S, _LU, 70, 45, "EUR", Decimal("15200.00"), "Basmati rice 25kg bags, 1 x 20ft container"),
    InvoiceSeed("INV-1015", _K, _CA, 80, 30, "GBP", Decimal("9300.00"), "Organic cotton towels, 410 cartons"),
    InvoiceSeed("INV-1016", _S, _GC, 55, 30, "AED", Decimal("62500.00"), "Assorted spice blends, 1 x 40ft container"),
    InvoiceSeed("INV-1017", _M, _NW, 25, 60, "USD", Decimal("22000.00"), "Precision valve assemblies, 8 pallets"),
    InvoiceSeed("INV-1018", _K, _AL, 20, 30, "EUR", Decimal("11000.00"), "Linen table covers, 260 cartons"),
    InvoiceSeed("INV-1019", _S, _HP, 15, 30, "USD", Decimal("7800.00"), "Dried red chilli, 1 x 20ft container"),
    InvoiceSeed("INV-1020", _M, _AN, 100, 30, "AED", Decimal("28000.00"), "Forged flange fittings, 6 pallets"),
    InvoiceSeed("INV-1021", _K, _TG, 10, 30, "GBP", Decimal("5200.00"), "Printed cotton scarves, 180 cartons"),
    InvoiceSeed("INV-1022", _S, _LU, 8, 30, "EUR", Decimal("9900.00"), "Cardamom and black pepper, 600 kg"),
    InvoiceSeed("INV-1023", _M, _NW, 5, 30, "USD", Decimal("3400.00"), "Machine tool spare parts (quote stage)", draft=True),
    InvoiceSeed("INV-1024", _M, _HP, 30, 45, "USD", Decimal("10000.00"), "Hydraulic pump housings, 10 pallets"),
]

# Initial bank statement already imported into the system (20 transactions).
PAYMENTS: list[PaymentSeed] = [
    PaymentSeed("TXN-1001", "INV-1010", _NW, "USD", Decimal("12500.00"), 24, "SIM-SWIFT-480011"),
    PaymentSeed("TXN-1002", "INV-1011", _AL, "EUR", Decimal("8400.00"), 18, "SIM-SWIFT-480012"),
    PaymentSeed("TXN-1003", "INV-1012", _TG, "GBP", Decimal("6750.00"), 9, "SIM-SWIFT-480013"),
    PaymentSeed("TXN-1004", "INV-1024", _HP, "USD", Decimal("6000.00"), 14, "SIM-SWIFT-480014"),
    PaymentSeed("TXN-1005", "INV-1024", _HP, "USD", Decimal("3500.00"), 6, "SIM-SWIFT-480015"),
    PaymentSeed("TXN-1006", "INV-1014", _LU, "EUR", Decimal("5000.00"), 40, "SIM-SWIFT-480016"),
    PaymentSeed("TXN-1007", "INV-1016", _GC, "AED", Decimal("30000.00"), 28, "SIM-SWIFT-480017"),
    PaymentSeed("TXN-1008", "INV-1017", _NW, "EUR", Decimal("22000.00"), 4, "SIM-SWIFT-480018"),
    PaymentSeed("TXN-1009", "INV-1018", _AL, "USD", Decimal("11000.00"), 3, "SIM-SWIFT-480019"),
    PaymentSeed("TXN-1010", "INV-1010", _NW, "USD", Decimal("12500.00"), 24, "SIM-SWIFT-480020"),
    PaymentSeed("TXN-1011", "INV-1012", _TG, "GBP", Decimal("6750.00"), 9, "SIM-SWIFT-480021"),
    PaymentSeed("TXN-1012", "PO-77821", _HP, "USD", Decimal("7750.00"), 7, "SIM-SWIFT-480022"),
    PaymentSeed("TXN-1013", "REMIT-5531", "Zenith Marine Exports Inc", "USD", Decimal("4250.00"), 12, "SIM-SWIFT-480023"),
    PaymentSeed("TXN-1014", None, "Unknown Remitter 8841", "AED", Decimal("15000.00"), 2, "SIM-SWIFT-480024"),
    PaymentSeed("TXN-1015", "INV-9999", "Sunrise Trading Co", "GBP", Decimal("2100.00"), 11, "SIM-SWIFT-480025"),
    PaymentSeed("TXN-1016", "ADV-2026-04", "Pacific Rim Traders", "USD", Decimal("9999.99"), 1, "SIM-SWIFT-480026"),
    PaymentSeed("TXN-1017", "INV-1022", "Delta Retail Partners GmbH", "EUR", Decimal("9900.00"), 2, "SIM-SWIFT-480027"),
    PaymentSeed("TXN-1018", None, "Caledonia Retail Group Limited", "GBP", Decimal("9300.00"), 5, "SIM-SWIFT-480028"),
    PaymentSeed("TXN-1019", "INV-1021", _TG, "GBP", Decimal("6000.00"), 3, "SIM-SWIFT-480029"),
    PaymentSeed("TXN-1020", "INV-1019", _HP, "USD", Decimal("7800.00"), 8, "SIM-SWIFT-480030"),
]

# A SECOND bank file, written to sample_data/payments.csv for the CSV-import demo. Values are strings
# on purpose: some rows are deliberately invalid to demonstrate validation and the error report.
IMPORT_DEMO_ROWS: list[dict[str, str | int]] = [
    # --- valid, new: these settle or progress existing invoices once reconciled
    {"ref": "TXN-2001", "pay": "INV-1013", "sender": _AN, "cur": "AED", "amt": "45000.00", "ago": 1, "bank": "SIM-SWIFT-480101"},
    {"ref": "TXN-2002", "pay": "INV-1024", "sender": _HP, "cur": "USD", "amt": "500.00", "ago": 1, "bank": "SIM-SWIFT-480102"},
    {"ref": "TXN-2003", "pay": "INV-1020", "sender": _AN, "cur": "AED", "amt": "28000.00", "ago": 1, "bank": "SIM-SWIFT-480103"},
    {"ref": "TXN-2004", "pay": "INV-1014", "sender": _LU, "cur": "EUR", "amt": "10200.00", "ago": 1, "bank": "SIM-SWIFT-480104"},
    # --- duplicates of transactions already in the database
    {"ref": "TXN-1003", "pay": "INV-1012", "sender": _TG, "cur": "GBP", "amt": "6750.00", "ago": 9, "bank": "SIM-SWIFT-480013"},
    {"ref": "TXN-1007", "pay": "INV-1016", "sender": _GC, "cur": "AED", "amt": "30000.00", "ago": 28, "bank": "SIM-SWIFT-480017"},
    # --- invalid rows (each fails a different validation rule)
    {"ref": "TXN-2005", "pay": "INV-1021", "sender": _TG, "cur": "XYZ", "amt": "1000.00", "ago": 1, "bank": "SIM-SWIFT-480105"},
    {"ref": "TXN-2006", "pay": "INV-1021", "sender": _TG, "cur": "GBP", "amt": "twelve hundred", "ago": 1, "bank": "SIM-SWIFT-480106"},
    {"ref": "TXN-2007", "pay": "INV-1021", "sender": _TG, "cur": "GBP", "amt": "1200.00", "ago": "31-13-2026", "bank": "SIM-SWIFT-480107"},
    {"ref": "TXN-2008", "pay": "INV-1021", "sender": "", "cur": "GBP", "amt": "1200.00", "ago": 1, "bank": "SIM-SWIFT-480108"},
]
