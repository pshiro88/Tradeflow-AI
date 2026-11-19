"""Seed demo data.

Usage (from backend/):
    python -m app.db.seed                 # RESET all data, then seed users + demo dataset
    python -m app.db.seed --users-only    # only ensure the 3 demo users exist (non-destructive)
    python -m app.db.seed --write-csv     # (re)write sample_data/invoices.csv and payments.csv

The full reset deletes every row in every table. It is meant for the local demo database.
"""

import argparse
import csv
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.base import Base
from app.db.seed_data import BUYERS, EXPORTERS, IMPORT_DEMO_ROWS, INVOICES, PAYMENTS, InvoiceSeed
from app.db.session import SessionLocal
from app.models.enums import InvoiceStatus, ReconciliationStatus, UserRole
from app.models.invoice import Invoice
from app.models.party import Buyer, Exporter
from app.models.payment import ImportBatch, Payment
from app.models.user import User
from app.services.reconciliation_service import ReconciliationService

# Demo-only credentials for a synthetic-data app. Listed in the README.
DEMO_PASSWORD = "Demo@12345"

DEMO_USERS: list[tuple[str, str, UserRole]] = [
    ("Asha Admin", "admin@example.com", UserRole.ADMIN),
    ("Farhan Finance", "finance@example.com", UserRole.FINANCE),
    ("Olivia Operations", "operations@example.com", UserRole.OPERATIONS),
]

SEED_BATCH_FILE_NAME = "bank_statement_initial.csv"
SAMPLE_DATA_DIR = Path(__file__).resolve().parents[3] / "sample_data"


def seed_users(db: Session) -> int:
    """Create any missing demo users. Returns the number created."""
    created = 0
    for full_name, email, role in DEMO_USERS:
        if db.scalar(select(User).where(User.email == email)) is None:
            db.add(User(full_name=full_name, email=email, password_hash=hash_password(DEMO_PASSWORD), role=role))
            created += 1
    db.flush()
    return created


def reset_all_data(db: Session) -> None:
    """Remove every row from every table.

    TRUNCATE is used instead of DELETE because payment allocations are append-only: a database
    trigger rejects row-level deletes (TRUNCATE does not fire row triggers).
    """
    names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    db.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
    db.flush()


def initial_invoice_status(seed: InvoiceSeed, due: date, today: date) -> InvoiceStatus:
    """Status before any payment is reconciled. The invoice service recomputes it from allocations later."""
    if seed.draft:
        return InvoiceStatus.DRAFT
    return InvoiceStatus.OVERDUE if due < today else InvoiceStatus.OPEN


def seed_demo_data(db: Session, today: date | None = None) -> dict[str, int]:
    """Insert exporters, buyers, invoices and the initial bank statement. Requires users to exist."""
    today = today or date.today()
    creator = db.scalar(select(User).where(User.role == UserRole.FINANCE))

    exporters = {e.company_name: Exporter(**vars_of(e)) for e in EXPORTERS}
    buyers = {b.buyer_name: Buyer(**vars_of(b)) for b in BUYERS}
    db.add_all([*exporters.values(), *buyers.values()])
    db.flush()

    for inv in INVOICES:
        invoice_date = today - timedelta(days=inv.invoice_days_ago)
        due_date = invoice_date + timedelta(days=inv.terms_days)
        db.add(
            Invoice(
                invoice_number=inv.invoice_number,
                exporter_id=exporters[inv.exporter].id,
                buyer_id=buyers[inv.buyer].id,
                invoice_date=invoice_date,
                due_date=due_date,
                currency=inv.currency,
                total_amount=inv.amount,
                description=inv.description,
                payment_terms=inv.payment_terms,
                status=initial_invoice_status(inv, due_date, today),
                created_by=creator.id if creator else None,
            )
        )

    batch = ImportBatch(
        file_name=SEED_BATCH_FILE_NAME,
        total_rows=len(PAYMENTS),
        accepted_rows=len(PAYMENTS),
        imported_by=creator.id if creator else None,
    )
    db.add(batch)
    db.flush()

    for p in PAYMENTS:
        db.add(
            Payment(
                transaction_reference=p.transaction_reference,
                payment_reference=p.payment_reference,
                sender_name=p.sender_name,
                currency=p.currency,
                amount=p.amount,
                transaction_date=today - timedelta(days=p.days_ago),
                bank_reference=p.bank_reference,
                import_batch_id=batch.id,
                status=ReconciliationStatus.PENDING,
            )
        )
    db.flush()
    return {
        "exporters": len(EXPORTERS),
        "buyers": len(BUYERS),
        "invoices": len(INVOICES),
        "payments": len(PAYMENTS),
    }


def vars_of(dataclass_instance: object) -> dict[str, object]:
    return dict(vars(dataclass_instance))


def write_sample_csvs(today: date | None = None, out_dir: Path = SAMPLE_DATA_DIR) -> list[Path]:
    """Write the reference invoice list and the demo bank file used for the CSV-import walkthrough."""
    today = today or date.today()
    out_dir.mkdir(parents=True, exist_ok=True)
    buyer_country = {b.buyer_name: b.country for b in BUYERS}

    invoices_path = out_dir / "invoices.csv"
    with invoices_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "invoice_number", "exporter_name", "buyer_name", "buyer_country", "invoice_date",
                "due_date", "currency", "invoice_amount", "description", "payment_terms",
            ]
        )
        for inv in INVOICES:
            invoice_date = today - timedelta(days=inv.invoice_days_ago)
            writer.writerow(
                [
                    inv.invoice_number, inv.exporter, inv.buyer, buyer_country[inv.buyer], invoice_date.isoformat(),
                    (invoice_date + timedelta(days=inv.terms_days)).isoformat(), inv.currency, inv.amount,
                    inv.description, inv.payment_terms,
                ]
            )

    payments_path = out_dir / "payments.csv"
    with payments_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "transaction_reference", "payment_reference", "sender_name", "currency", "amount",
                "transaction_date", "bank_reference",
            ]
        )
        for row in IMPORT_DEMO_ROWS:
            ago = row["ago"]
            tx_date = ago if isinstance(ago, str) else (today - timedelta(days=ago)).isoformat()
            writer.writerow([row["ref"], row["pay"], row["sender"], row["cur"], row["amt"], tx_date, row["bank"]])

    return [invoices_path, payments_path]


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed TradeFlow demo data.")
    parser.add_argument("--users-only", action="store_true", help="only create missing demo users")
    parser.add_argument("--write-csv", action="store_true", help="only (re)write the sample_data CSV and PDF files")
    parser.add_argument("--no-reconcile", action="store_true", help="leave the seeded payments PENDING (skip the reconciliation run)")
    args = parser.parse_args()

    if args.write_csv:
        from app.db.sample_documents import write_sample_documents
        from app.db.sample_packs import write_payment_packs

        for path in [*write_sample_csvs(), *write_payment_packs(), *write_sample_documents()]:
            print(f"Wrote {path}")
        return

    with SessionLocal() as db:
        if args.users_only:
            print(f"Seeded {seed_users(db)} new demo user(s).")
        else:
            reset_all_data(db)
            seed_users(db)
            counts = seed_demo_data(db)
            db.commit()
            print("Reset database and seeded:", ", ".join(f"{n} {k}" for k, n in counts.items()), "+ 3 users")
            if not args.no_reconcile:
                finance = db.scalar(select(User).where(User.role == UserRole.FINANCE))
                summary = ReconciliationService(db).run(finance)
                print(f"Reconciled {summary.processed} payments:", ", ".join(f"{n} {k}" for k, n in sorted(summary.counts.items())))
            # Regenerate the sample CSVs and PDFs from the SAME dates, so the files you upload always agree with
            # the database (otherwise a day-old seed would show date differences in the document checks).
            from app.db.sample_documents import write_sample_documents
            from app.db.sample_packs import write_payment_packs

            files = [*write_sample_csvs(), *write_payment_packs(), *write_sample_documents()]
            print(f"Refreshed {len(files)} sample files in sample_data/")
        db.commit()


if __name__ == "__main__":
    main()
