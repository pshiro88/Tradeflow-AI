import uuid

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.invoice import Invoice
from app.models.user import User
from app.schemas.document import DocumentFilters


class DocumentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _apply_filters(stmt: Select, f: DocumentFilters) -> Select:
        if f.invoice_id:
            stmt = stmt.where(Document.invoice_id == f.invoice_id)
        if f.document_type:
            stmt = stmt.where(Document.document_type == f.document_type)
        if f.extraction_status:
            stmt = stmt.where(Document.extraction_status == f.extraction_status)
        if f.verification_status:
            stmt = stmt.where(Document.verification_status == f.verification_status)
        if f.search:
            term = f"%{f.search.strip()}%"
            stmt = stmt.where(or_(Document.file_name.ilike(term), Invoice.invoice_number.ilike(term)))
        return stmt

    def list_page(
        self, f: DocumentFilters, *, page: int, page_size: int
    ) -> tuple[list[tuple[Document, str | None, str | None]], int]:
        base = select(Document.id).outerjoin(Invoice, Invoice.id == Document.invoice_id)
        total = self.db.scalar(select(func.count()).select_from(self._apply_filters(base, f).subquery())) or 0
        stmt = (
            self._apply_filters(
                select(Document, Invoice.invoice_number, User.full_name)
                .outerjoin(Invoice, Invoice.id == Document.invoice_id)
                .outerjoin(User, User.id == Document.uploaded_by),
                f,
            )
            .order_by(Document.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return [(d, n, u) for d, n, u in self.db.execute(stmt).all()], total

    def get_row(self, document_id: uuid.UUID) -> tuple[Document, str | None, str | None] | None:
        stmt = (
            select(Document, Invoice.invoice_number, User.full_name)
            .outerjoin(Invoice, Invoice.id == Document.invoice_id)
            .outerjoin(User, User.id == Document.uploaded_by)
            .where(Document.id == document_id)
        )
        row = self.db.execute(stmt).first()
        return (row[0], row[1], row[2]) if row else None

    def lock(self, document_id: uuid.UUID, *, nowait: bool = False) -> Document | None:
        stmt = select(Document).where(Document.id == document_id).with_for_update(nowait=nowait)
        return self.db.scalars(stmt).first()

    def add(self, document: Document) -> Document:
        self.db.add(document)
        self.db.flush()
        return document

    def invoice_exists(self, invoice_id: uuid.UUID) -> bool:
        return self.db.scalar(select(Invoice.id).where(Invoice.id == invoice_id)) is not None

    def get_invoice(self, invoice_id: uuid.UUID) -> Invoice | None:
        return self.db.execute(select(Invoice).where(Invoice.id == invoice_id)).unique().scalar_one_or_none()
