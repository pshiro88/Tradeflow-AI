import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin, enum_type
from app.models.enums import DocumentStatus, DocumentType, ExtractionStatus


class Document(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "documents"

    invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoices.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    document_type: Mapped[DocumentType] = mapped_column(enum_type(DocumentType, "document_type"), nullable=False)
    extraction_status: Mapped[ExtractionStatus] = mapped_column(
        enum_type(ExtractionStatus, "extraction_status"), nullable=False, default=ExtractionStatus.NOT_STARTED
    )
    verification_status: Mapped[DocumentStatus] = mapped_column(
        enum_type(DocumentStatus, "document_status"), nullable=False, default=DocumentStatus.UPLOADED
    )
    # AI-extracted fields (draft) and the user-confirmed version. Money fields are strings to avoid floats.
    extracted_data: Mapped[dict | None] = mapped_column(JSONB)
    confirmed_data: Mapped[dict | None] = mapped_column(JSONB)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class ComplianceCheck(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Operational document-completeness check (not a regulatory compliance engine)."""

    __tablename__ = "compliance_checks"

    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        enum_type(DocumentStatus, "document_status"), nullable=False, default=DocumentStatus.NOT_UPLOADED
    )
    remarks: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
