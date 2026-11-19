import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, require_role
from app.core.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.common import Page
from app.schemas.compliance import CheckRequest, Checklist, OverviewFilters, OverviewItem
from app.services.compliance_service import ComplianceService

router = APIRouter(prefix="/compliance", tags=["compliance"])

# Document completeness is an Operations responsibility (ADMIN is always allowed).
OperationsUser = Annotated[User, Depends(require_role(UserRole.OPERATIONS))]


@router.get("", response_model=Page[OverviewItem])
def overview(
    db: DbSession,
    _user: OperationsUser,
    filters: Annotated[OverviewFilters, Query()],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Page[OverviewItem]:
    """Every issued invoice with its document-checklist progress, incomplete ones first."""
    return ComplianceService(db).overview(filters, page=page, page_size=page_size)


@router.get("/{invoice_id}", response_model=Checklist)
def get_checklist(invoice_id: uuid.UUID, db: DbSession, _user: OperationsUser) -> Checklist:
    """The document checklist for one invoice, including differences between documents and the invoice."""
    return ComplianceService(db).checklist(invoice_id)


@router.post("/{invoice_id}/checks", response_model=Checklist)
def record_check(invoice_id: uuid.UUID, payload: CheckRequest, db: DbSession, user: OperationsUser) -> Checklist:
    """Record a person's review of one checklist item. Recorded in the audit log; earlier reviews are kept."""
    return ComplianceService(db).add_check(invoice_id, payload, user)
