import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUser, DbSession, require_role
from app.core.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.invoice_repository import SortDir, SortField
from app.schemas.common import Page
from app.schemas.invoice import (
    InvoiceCreate,
    InvoiceDetail,
    InvoiceFilters,
    InvoiceListItem,
    InvoiceStatusUpdate,
    InvoiceUpdate,
    PartyOut,
)
from app.schemas.compliance import Lifecycle
from app.services.compliance_service import ComplianceService
from app.services.invoice_service import InvoiceService

router = APIRouter(prefix="/invoices", tags=["invoices"])

# Creating and changing invoices is a Finance responsibility (ADMIN is always allowed).
FinanceUser = Annotated[User, Depends(require_role(UserRole.FINANCE))]


@router.get("", response_model=Page[InvoiceListItem])
def list_invoices(
    db: DbSession,
    _user: CurrentUser,
    filters: Annotated[InvoiceFilters, Query()],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    sort_by: SortField = "invoice_date",
    sort_dir: SortDir = "desc",
) -> Page[InvoiceListItem]:
    return InvoiceService(db).list_invoices(filters, page=page, page_size=page_size, sort_by=sort_by, sort_dir=sort_dir)


@router.get("/exporters", response_model=list[PartyOut])
def list_exporters(db: DbSession, _user: CurrentUser) -> list[PartyOut]:
    """Exporter profiles for the invoice form."""
    return InvoiceService(db).list_exporters()


@router.get("/buyers", response_model=list[PartyOut])
def list_buyers(db: DbSession, _user: CurrentUser) -> list[PartyOut]:
    """Known buyers, used for suggestions and the buyer filter."""
    return InvoiceService(db).list_buyers()


@router.post("", response_model=InvoiceDetail, status_code=status.HTTP_201_CREATED)
def create_invoice(payload: InvoiceCreate, db: DbSession, user: FinanceUser) -> InvoiceDetail:
    return InvoiceService(db).create_invoice(payload, user)


@router.get("/{invoice_id}", response_model=InvoiceDetail)
def get_invoice(invoice_id: uuid.UUID, db: DbSession, _user: CurrentUser) -> InvoiceDetail:
    return InvoiceService(db).get_invoice(invoice_id)


@router.get("/{invoice_id}/lifecycle", response_model=Lifecycle)
def get_lifecycle(invoice_id: uuid.UUID, db: DbSession, _user: CurrentUser) -> Lifecycle:
    """Progress from issue to 'ready for export filing' (a simulated checklist). Counts only; no document contents."""
    return ComplianceService(db).lifecycle(invoice_id)


@router.put("/{invoice_id}", response_model=InvoiceDetail)
def update_invoice(invoice_id: uuid.UUID, payload: InvoiceUpdate, db: DbSession, user: FinanceUser) -> InvoiceDetail:
    return InvoiceService(db).update_invoice(invoice_id, payload, user)


@router.patch("/{invoice_id}/status", response_model=InvoiceDetail)
def change_invoice_status(
    invoice_id: uuid.UUID, payload: InvoiceStatusUpdate, db: DbSession, user: FinanceUser
) -> InvoiceDetail:
    """Publish a draft (OPEN) or cancel an invoice. There is deliberately no DELETE endpoint."""
    return InvoiceService(db).change_status(invoice_id, payload.status, user)
