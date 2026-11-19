import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, require_role
from app.core.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.common import Page
from app.schemas.reconciliation import (
    ApproveRequest,
    EligibleInvoice,
    ReconciliationDetail,
    ReconciliationFilters,
    ReconciliationItem,
    RejectRequest,
    RunSummary,
    StatusSummary,
)
from app.services.reconciliation_service import ReconciliationService

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])

# Reconciliation is a Finance responsibility (ADMIN is always allowed).
FinanceUser = Annotated[User, Depends(require_role(UserRole.FINANCE))]


@router.post("/run", response_model=RunSummary)
def run_reconciliation(db: DbSession, user: FinanceUser) -> RunSummary:
    """Reconcile all pending payments. Safe to call repeatedly: processed payments are never revisited."""
    return ReconciliationService(db).run(user)


@router.get("/summary", response_model=StatusSummary)
def reconciliation_summary(db: DbSession, _user: FinanceUser) -> StatusSummary:
    return ReconciliationService(db).summary()


@router.get("", response_model=Page[ReconciliationItem])
def list_results(
    db: DbSession,
    _user: FinanceUser,
    filters: Annotated[ReconciliationFilters, Query()],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Page[ReconciliationItem]:
    return ReconciliationService(db).list_results(filters, page=page, page_size=page_size)


@router.get("/{result_id}", response_model=ReconciliationDetail)
def get_result(result_id: uuid.UUID, db: DbSession, _user: FinanceUser) -> ReconciliationDetail:
    return ReconciliationService(db).get_result(result_id)


@router.get("/{result_id}/eligible-invoices", response_model=list[EligibleInvoice])
def eligible_invoices(result_id: uuid.UUID, db: DbSession, _user: FinanceUser) -> list[EligibleInvoice]:
    """Invoices this payment could be manually allocated to (same currency, payable, balance remaining)."""
    return ReconciliationService(db).eligible_invoices(result_id)


@router.post("/{result_id}/approve", response_model=ReconciliationDetail)
def approve_result(result_id: uuid.UUID, payload: ApproveRequest, db: DbSession, user: FinanceUser) -> ReconciliationDetail:
    """Manually allocate a payment to an invoice. Recorded in the audit log."""
    return ReconciliationService(db).approve(result_id, payload, user)


@router.post("/{result_id}/reject", response_model=ReconciliationDetail)
def reject_result(result_id: uuid.UUID, payload: RejectRequest, db: DbSession, user: FinanceUser) -> ReconciliationDetail:
    """Reject the suggested candidate. Recorded in the audit log."""
    return ReconciliationService(db).reject(result_id, payload, user)
