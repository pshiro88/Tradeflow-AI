from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, require_role
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.dashboard import (
    CurrencyDistribution,
    DashboardFilters,
    DashboardSummary,
    OutstandingInvoice,
    PaymentDistribution,
    PaymentTrends,
    RecentTransaction,
)
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# The dashboard exposes payment data, so it follows the same rule as the payments module:
# Finance (and Admin, who may do everything).
FinanceUser = Annotated[User, Depends(require_role(UserRole.FINANCE))]
Filters = Annotated[DashboardFilters, Query()]


@router.get("/summary", response_model=DashboardSummary)
def summary(db: DbSession, _user: FinanceUser, filters: Filters) -> DashboardSummary:
    return DashboardService(db).summary(filters)


@router.get("/payment-trends", response_model=PaymentTrends)
def payment_trends(
    db: DbSession, _user: FinanceUser, filters: Filters, months: Annotated[int, Query(ge=1, le=24)] = 6
) -> PaymentTrends:
    """Monthly invoiced vs received in a single currency (the `currency` filter, or the main one)."""
    return DashboardService(db).payment_trends(filters, months)


@router.get("/payment-distribution", response_model=PaymentDistribution)
def payment_distribution(db: DbSession, _user: FinanceUser, filters: Filters) -> PaymentDistribution:
    return DashboardService(db).payment_distribution(filters)


@router.get("/currency-distribution", response_model=CurrencyDistribution)
def currency_distribution(db: DbSession, _user: FinanceUser, filters: Filters) -> CurrencyDistribution:
    return DashboardService(db).currency_distribution(filters)


@router.get("/recent-transactions", response_model=list[RecentTransaction])
def recent_transactions(
    db: DbSession, _user: FinanceUser, filters: Filters, limit: Annotated[int, Query(ge=1, le=50)] = 8
) -> list[RecentTransaction]:
    return DashboardService(db).recent_transactions(filters, limit)


@router.get("/outstanding-invoices", response_model=list[OutstandingInvoice])
def outstanding_invoices(
    db: DbSession, _user: FinanceUser, filters: Filters, limit: Annotated[int, Query(ge=1, le=50)] = 6
) -> list[OutstandingInvoice]:
    """Issued invoices that still have a balance, oldest due date first."""
    return DashboardService(db).outstanding_invoices(filters, limit)
