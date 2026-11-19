import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, ConflictError, NotFoundError
from app.models.enums import InvoiceStatus
from app.models.invoice import Invoice
from app.models.party import Buyer
from app.models.user import User
from app.repositories.invoice_repository import InvoiceRepository, SortDir, SortField
from app.schemas.common import Page
from app.schemas.invoice import (
    InvoiceCreate,
    InvoiceDetail,
    InvoiceFilters,
    InvoiceListItem,
    InvoicePaymentOut,
    InvoiceUpdate,
    PartyOut,
)
from app.services.audit_service import record_audit
from app.services.invoice_status import derive_status

ZERO = Decimal("0.00")


class InvoiceService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = InvoiceRepository(db)

    # ------------------------------------------------------------------ reads

    def list_invoices(
        self,
        filters: InvoiceFilters,
        *,
        page: int,
        page_size: int,
        sort_by: SortField,
        sort_dir: SortDir,
        today: date | None = None,
    ) -> Page[InvoiceListItem]:
        today = today or date.today()
        rows, total = self.repo.list_page(
            filters, today=today, page=page, page_size=page_size, sort_by=sort_by, sort_dir=sort_dir
        )
        items = [self._list_item(inv, received, status) for inv, received, status in rows]
        return Page.build(items, total, page, page_size)

    def get_invoice(self, invoice_id: uuid.UUID, today: date | None = None) -> InvoiceDetail:
        row = self.repo.get_with_totals(invoice_id, today or date.today())
        if row is None:
            raise NotFoundError("Invoice not found")
        return self._detail(*row)

    def list_exporters(self) -> list[PartyOut]:
        return [PartyOut(id=e.id, name=e.company_name, country=e.country) for e in self.repo.list_exporters()]

    def list_buyers(self) -> list[PartyOut]:
        return [PartyOut(id=b.id, name=b.buyer_name, country=b.country) for b in self.repo.list_buyers()]

    # ------------------------------------------------------------------ writes

    def create_invoice(self, payload: InvoiceCreate, user: User) -> InvoiceDetail:
        if self.repo.number_exists(payload.invoice_number):
            raise ConflictError(f"Invoice number {payload.invoice_number} already exists")
        if self.repo.get_exporter(payload.exporter_id) is None:
            raise BusinessValidationError("Exporter not found")

        buyer = self._find_or_create_buyer(payload.buyer_name, payload.buyer_country)
        invoice = Invoice(
            invoice_number=payload.invoice_number,
            exporter_id=payload.exporter_id,
            buyer_id=buyer.id,
            invoice_date=payload.invoice_date,
            due_date=payload.due_date,
            currency=payload.currency,
            total_amount=payload.total_amount,
            description=payload.description,
            payment_terms=payload.payment_terms,
            status=payload.status,
            created_by=user.id,
        )
        invoice = self._save_new(invoice)
        self._sync_stored_status(invoice, ZERO)
        record_audit(
            self.db,
            user_id=user.id,
            action="INVOICE_CREATED",
            entity_type="invoice",
            entity_id=invoice.id,
            new_values=self._snapshot(invoice),
        )
        self.db.commit()
        return self.get_invoice(invoice.id)

    def update_invoice(self, invoice_id: uuid.UUID, payload: InvoiceUpdate, user: User) -> InvoiceDetail:
        invoice = self._get_locked(invoice_id)
        if invoice.status == InvoiceStatus.CANCELLED:
            raise ConflictError("Cancelled invoices cannot be edited")
        if self.repo.number_exists(payload.invoice_number, exclude_id=invoice.id):
            raise ConflictError(f"Invoice number {payload.invoice_number} already exists")
        if self.repo.get_exporter(payload.exporter_id) is None:
            raise BusinessValidationError("Exporter not found")

        received = self.repo.received_total(invoice.id)
        buyer = self._find_or_create_buyer(payload.buyer_name, payload.buyer_country)

        if received > 0:
            # Payments are already allocated: fields that give those allocations meaning are frozen.
            locked_changes = {
                "invoice number": payload.invoice_number != invoice.invoice_number,
                "currency": payload.currency != invoice.currency,
                "exporter": payload.exporter_id != invoice.exporter_id,
                "buyer": buyer.id != invoice.buyer_id,
            }
            changed = [name for name, did_change in locked_changes.items() if did_change]
            if changed:
                raise ConflictError(f"Cannot change {', '.join(changed)}: payments are already recorded")
            if payload.total_amount < received:
                raise BusinessValidationError(
                    f"Invoice amount cannot be lower than the amount already received ({received})"
                )

        before = self._snapshot(invoice)
        invoice.invoice_number = payload.invoice_number
        invoice.exporter_id = payload.exporter_id
        invoice.buyer_id = buyer.id
        invoice.invoice_date = payload.invoice_date
        invoice.due_date = payload.due_date
        invoice.currency = payload.currency
        invoice.total_amount = payload.total_amount
        invoice.description = payload.description
        invoice.payment_terms = payload.payment_terms
        self._sync_stored_status(invoice, received)

        record_audit(
            self.db,
            user_id=user.id,
            action="INVOICE_UPDATED",
            entity_type="invoice",
            entity_id=invoice.id,
            old_values=before,
            new_values=self._snapshot(invoice),
        )
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError(f"Invoice number {payload.invoice_number} already exists") from exc
        return self.get_invoice(invoice.id)

    def change_status(self, invoice_id: uuid.UUID, new_status: InvoiceStatus, user: User) -> InvoiceDetail:
        """Manual transitions only: DRAFT -> OPEN (publish) and any live invoice -> CANCELLED."""
        invoice = self._get_locked(invoice_id)
        before = self._snapshot(invoice)
        received = self.repo.received_total(invoice.id)

        if new_status == InvoiceStatus.OPEN:
            if invoice.status != InvoiceStatus.DRAFT:
                raise ConflictError("Only draft invoices can be published")
            invoice.status = InvoiceStatus.OPEN
            self._sync_stored_status(invoice, received)
            action = "INVOICE_PUBLISHED"
        else:  # CANCELLED
            if invoice.status == InvoiceStatus.CANCELLED:
                raise ConflictError("Invoice is already cancelled")
            if received > 0:
                raise ConflictError(
                    "This invoice has payments recorded and cannot be cancelled. Review the allocations first."
                )
            invoice.status = InvoiceStatus.CANCELLED
            action = "INVOICE_CANCELLED"

        record_audit(
            self.db,
            user_id=user.id,
            action=action,
            entity_type="invoice",
            entity_id=invoice.id,
            old_values={"status": before["status"]},
            new_values={"status": invoice.status},
        )
        self.db.commit()
        return self.get_invoice(invoice.id)

    # ------------------------------------------------------------------ helpers

    def _get_locked(self, invoice_id: uuid.UUID) -> Invoice:
        invoice = self.repo.get(invoice_id, for_update=True)
        if invoice is None:
            raise NotFoundError("Invoice not found")
        return invoice

    def _save_new(self, invoice: Invoice) -> Invoice:
        try:
            return self.repo.add(invoice)
        except IntegrityError as exc:  # lost a race on the unique invoice_number
            self.db.rollback()
            raise ConflictError(f"Invoice number {invoice.invoice_number} already exists") from exc

    def _find_or_create_buyer(self, name: str, country: str) -> Buyer:
        """Reuse a buyer with the same name (case-insensitive); otherwise create one."""
        existing = self.repo.find_buyer_by_name(name)
        if existing:
            return existing
        return self.repo.add_buyer(Buyer(buyer_name=name, country=country))

    def _sync_stored_status(self, invoice: Invoice, received: Decimal) -> None:
        """Keep the persisted status column aligned with the derived value (DRAFT/CANCELLED untouched)."""
        invoice.status = derive_status(invoice.status, invoice.total_amount, received, invoice.due_date, date.today())

    @staticmethod
    def _snapshot(invoice: Invoice) -> dict:
        return {
            "invoice_number": invoice.invoice_number,
            "exporter_id": invoice.exporter_id,
            "buyer_id": invoice.buyer_id,
            "invoice_date": invoice.invoice_date,
            "due_date": invoice.due_date,
            "currency": invoice.currency,
            "total_amount": invoice.total_amount,
            "description": invoice.description,
            "payment_terms": invoice.payment_terms,
            "status": invoice.status,
        }

    @staticmethod
    def _list_item(invoice: Invoice, received: Decimal, status: str) -> InvoiceListItem:
        return InvoiceListItem(
            id=invoice.id,
            invoice_number=invoice.invoice_number,
            buyer_name=invoice.buyer.buyer_name,
            buyer_country=invoice.buyer.country,
            exporter_name=invoice.exporter.company_name,
            invoice_date=invoice.invoice_date,
            due_date=invoice.due_date,
            currency=invoice.currency,
            total_amount=invoice.total_amount,
            amount_received=received,
            outstanding_amount=max(invoice.total_amount - received, ZERO),
            status=InvoiceStatus(status),
        )

    def _detail(self, invoice: Invoice, received: Decimal, status: str) -> InvoiceDetail:
        base = self._list_item(invoice, received, status)
        payments = [
            InvoicePaymentOut(
                id=alloc.id,
                payment_id=payment.id,
                transaction_reference=payment.transaction_reference,
                sender_name=payment.sender_name,
                transaction_date=payment.transaction_date,
                allocated_amount=alloc.allocated_amount,
                currency=alloc.currency,
                allocation_type=alloc.allocation_type,
                created_at=alloc.created_at,
            )
            for alloc, payment in self.repo.payments_for(invoice.id)
        ]
        return InvoiceDetail(
            **base.model_dump(),
            exporter_id=invoice.exporter_id,
            buyer_id=invoice.buyer_id,
            description=invoice.description,
            payment_terms=invoice.payment_terms,
            created_at=invoice.created_at,
            updated_at=invoice.updated_at,
            payments=payments,
            has_payments=received > 0,
            is_editable=invoice.status != InvoiceStatus.CANCELLED,
        )
