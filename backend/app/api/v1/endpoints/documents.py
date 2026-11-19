import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from app.api.deps import DbSession, require_role
from app.core.config import get_settings
from app.core.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core.errors import BusinessValidationError
from app.models.enums import DocumentType, UserRole
from app.models.user import User
from app.schemas.common import Page
from app.schemas.document import (
    DocumentDetail,
    DocumentExplanation,
    DocumentFilters,
    DocumentListItem,
    VerifyRequest,
)
from app.services.document_service import DocumentService
from app.services.ollama_service import LLMClient, get_llm

router = APIRouter(prefix="/documents", tags=["documents"])

# Trade documents are an Operations responsibility (ADMIN is always allowed).
OperationsUser = Annotated[User, Depends(require_role(UserRole.OPERATIONS))]
Llm = Annotated[LLMClient, Depends(get_llm)]


@router.post("/upload", response_model=DocumentDetail, status_code=status.HTTP_201_CREATED)
def upload_document(
    db: DbSession,
    user: OperationsUser,
    file: Annotated[UploadFile, File(...)],
    document_type: Annotated[DocumentType, Form()],
    invoice_id: Annotated[uuid.UUID | None, Form()] = None,
) -> DocumentDetail:
    """Upload a text-based PDF. It is validated and stored; AI extraction is a separate, explicit step."""
    if not file.filename:
        raise BusinessValidationError("A file name is required")
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    content = file.file.read(max_bytes + 1)  # one byte over the limit is enough to detect an oversized upload
    return DocumentService(db).upload(content, file.filename, document_type, invoice_id, user)


@router.get("", response_model=Page[DocumentListItem])
def list_documents(
    db: DbSession,
    _user: OperationsUser,
    filters: Annotated[DocumentFilters, Query()],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Page[DocumentListItem]:
    return DocumentService(db).list_documents(filters, page=page, page_size=page_size)


@router.get("/invoice/{invoice_id}", response_model=Page[DocumentListItem])
def documents_for_invoice(
    invoice_id: uuid.UUID,
    db: DbSession,
    _user: OperationsUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Page[DocumentListItem]:
    return DocumentService(db).list_documents(DocumentFilters(invoice_id=invoice_id), page=page, page_size=page_size)


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document_id: uuid.UUID, db: DbSession, _user: OperationsUser) -> DocumentDetail:
    return DocumentService(db).get(document_id)


@router.post("/{document_id}/extract", response_model=DocumentDetail)
def extract_document(document_id: uuid.UUID, db: DbSession, user: OperationsUser, llm: Llm) -> DocumentDetail:
    """Run local AI extraction. The result is a draft for a person to review (503 if Ollama is unavailable)."""
    return DocumentService(db).extract(document_id, user, llm)


@router.post("/{document_id}/verify", response_model=DocumentDetail)
def verify_document(document_id: uuid.UUID, payload: VerifyRequest, db: DbSession, user: OperationsUser) -> DocumentDetail:
    """A person confirms (optionally correcting the values) or rejects the document."""
    return DocumentService(db).verify(document_id, payload, user)


@router.post("/{document_id}/explain", response_model=DocumentExplanation)
def explain_document(document_id: uuid.UUID, db: DbSession, user: OperationsUser, llm: Llm) -> DocumentExplanation:
    """Plain-language summary: what was extracted, what is missing, what disagrees with the linked invoice."""
    return DocumentService(db).explain(document_id, user, llm)
