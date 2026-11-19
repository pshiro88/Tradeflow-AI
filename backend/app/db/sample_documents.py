"""Generate fictional, text-based commercial-invoice PDFs for the document-intelligence demo.

Usage (from backend/):  python -m app.db.sample_documents

The PDFs mirror seeded invoices (same number, parties, currency, amount and dates), so extraction results can
be compared against the database. One file deliberately carries a different amount to show the consistency check.
All names and amounts are fictional.
"""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pymupdf

from app.db.seed_data import BUYERS, EXPORTERS, INVOICES, InvoiceSeed

SAMPLE_DOCUMENTS_DIR = Path(__file__).resolve().parents[3] / "sample_data" / "documents"

# (invoice number, file name, amount difference, date style)
SAMPLES: list[tuple[str, str, Decimal, str]] = [
    ("INV-1024", "INV-1024_commercial_invoice.pdf", Decimal("0"), "long"),
    ("INV-1021", "INV-1021_commercial_invoice.pdf", Decimal("0"), "iso"),
    ("INV-1022", "INV-1022_commercial_invoice.pdf", Decimal("0"), "long"),
    ("INV-1018", "INV-1018_commercial_invoice_amount_differs.pdf", Decimal("500.00"), "iso"),
]


def _fmt_date(d: date, style: str) -> str:
    return d.isoformat() if style == "iso" else f"{d.day} {d.strftime('%B %Y')}"


def render_invoice_pdf(inv: InvoiceSeed, today: date, *, amount_delta: Decimal = Decimal("0"), date_style: str = "long") -> bytes:
    exporter = next(e for e in EXPORTERS if e.company_name == inv.exporter)
    buyer = next(b for b in BUYERS if b.buyer_name == inv.buyer)
    invoice_date = today - timedelta(days=inv.invoice_days_ago)
    due_date = invoice_date + timedelta(days=inv.terms_days)
    total = inv.amount + amount_delta
    qty = 10
    unit = (total / qty).quantize(Decimal("0.01"))
    lines = [
        ("COMMERCIAL INVOICE", 20, 72),
        (f"Invoice No: {inv.invoice_number}", 11, 110),
        (f"Invoice Date: {_fmt_date(invoice_date, date_style)}", 11, 126),
        (f"Due Date: {_fmt_date(due_date, date_style)}", 11, 142),
        (f"Payment Terms: {inv.payment_terms}", 11, 158),
        ("", 11, 174),
        (f"Exporter: {exporter.company_name}", 11, 190),
        (f"Exporter Country: {exporter.country}", 11, 206),
        (f"Buyer: {buyer.buyer_name}", 11, 232),
        (f"Buyer Country: {buyer.country}", 11, 248),
        (f"Description of goods: {inv.description}", 11, 280),
        (f"Quantity: {qty} units     Unit price: {inv.currency} {unit:,.2f}", 11, 296),
        (f"Currency: {inv.currency}", 11, 328),
        (f"Total Amount: {inv.currency} {total:,.2f}", 13, 344),
        ("Declaration: We certify that this invoice shows the actual price of the goods described.", 9, 392),
        ("This is a fictional document for software demonstration only.", 9, 408),
    ]
    doc = pymupdf.open()
    page = doc.new_page()
    for text, size, y in lines:
        if text:
            page.insert_text((72, y), text, fontsize=size)
    data = doc.tobytes()
    doc.close()
    return data


def write_sample_documents(today: date | None = None, out_dir: Path = SAMPLE_DOCUMENTS_DIR) -> list[Path]:
    today = today or date.today()
    out_dir.mkdir(parents=True, exist_ok=True)
    by_number = {i.invoice_number: i for i in INVOICES}
    written = []
    for number, file_name, delta, style in SAMPLES:
        path = out_dir / file_name
        path.write_bytes(render_invoice_pdf(by_number[number], today, amount_delta=delta, date_style=style))
        written.append(path)
    return written


if __name__ == "__main__":
    for path in write_sample_documents():
        print(f"Wrote {path}")
