from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, require_role
from app.core.constants import MAX_PAGE_SIZE
from app.models.user import User
from app.schemas.audit import AIAuditFilters, AIAuditItem, AuditFilters, AuditLogItem, AuditOptions
from app.schemas.common import Page
from app.services.audit_query_service import AuditQueryService

router = APIRouter(prefix="/audit-logs", tags=["audit"])

# No roles listed: only ADMIN passes require_role().
AdminUser = Annotated[User, Depends(require_role())]
PageNo = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]


@router.get("", response_model=Page[AuditLogItem])
def activity_logs(
    db: DbSession, _admin: AdminUser, filters: Annotated[AuditFilters, Query()], page: PageNo = 1, page_size: PageSize = 25
) -> Page[AuditLogItem]:
    """Who did what, and what changed (old and new values). Newest first."""
    return AuditQueryService(db).activity(filters, page=page, page_size=page_size)


@router.get("/ai", response_model=Page[AIAuditItem])
def ai_request_logs(
    db: DbSession, _admin: AdminUser, filters: Annotated[AIAuditFilters, Query()], page: PageNo = 1, page_size: PageSize = 25
) -> Page[AIAuditItem]:
    """Every call to the local AI model: operation, model, status and how long it took. Never document text."""
    return AuditQueryService(db).ai_requests(filters, page=page, page_size=page_size)


@router.get("/options", response_model=AuditOptions)
def audit_options(db: DbSession, _admin: AdminUser) -> AuditOptions:
    """Values for the filter drop-downs."""
    return AuditQueryService(db).options()
