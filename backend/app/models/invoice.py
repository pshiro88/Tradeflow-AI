import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_type
from app.models.enums import InvoiceStatus
from app.models.party import Buyer, Exporter


class Invoice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint("total_amount > 0", name="ck_invoices_total_amount_positive"),
        CheckConstraint("due_date >= invoice_date", name="ck_invoices_due_after_invoice_date"),
    )

    invoice_number: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    exporter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exporters.id"), nullable=False)
    buyer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("buyers.id"), nullable=False, index=True)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    payment_terms: Mapped[str | None] = mapped_column(String(100))
    # Derived from allocations + due date by the invoice service (never freely user-set).
    status: Mapped[InvoiceStatus] = mapped_column(
        enum_type(InvoiceStatus, "invoice_status"), nullable=False, default=InvoiceStatus.OPEN, index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    exporter: Mapped[Exporter] = relationship(lazy="joined")
    buyer: Mapped[Buyer] = relationship(lazy="joined")
