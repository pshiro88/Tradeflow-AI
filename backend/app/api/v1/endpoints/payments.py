import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status

from app.api.deps import DbSession, require_role
from app.core.config import get_settings
from app.core.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core.errors import BusinessValidationError
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.payment_repository import SortDir, SortField
from app.schemas.common import Page
from app.schemas.payment import ImportBatchDetail, ImportBatchOut, PaymentDetail, PaymentFilters, PaymentListItem
from app.services.payment_service import PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])

# Payment data is a Finance responsibility (ADMIN is always allowed).
FinanceUser = Annotated[User, Depends(require_role(UserRole.FINANCE))]


@router.post("/import", response_model=ImportBatchDetail, status_code=status.HTTP_201_CREATED)
def import_payments(db: DbSession, user: FinanceUser, file: Annotated[UploadFile, File(...)]) -> ImportBatchDetail:
    """Import a bank-transaction CSV. Returns the batch summary including every rejected row."""
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    if not file.filename:
        raise BusinessValidationError("A file name is required")
    # Read one byte past the limit so an oversized upload is detected without loading all of it.
    content = file.file.read(max_bytes + 1)
    return PaymentService(db).import_csv(content, file.filename, user)


@router.get("/imports", response_model=list[ImportBatchOut])
def list_imports(db: DbSession, _user: FinanceUser, limit: Annotated[int, Query(ge=1, le=50)] = 10) -> list[ImportBatchOut]:
    """Most recent import batches."""
    return PaymentService(db).recent_batches(limit)


@router.get("/imports/{batch_id}", response_model=ImportBatchDetail)
def get_import(batch_id: uuid.UUID, db: DbSession, _user: FinanceUser) -> ImportBatchDetail:
    return PaymentService(db).get_batch(batch_id)


@router.get("/imports/{batch_id}/errors.csv")
def download_import_errors(batch_id: uuid.UUID, db: DbSession, _user: FinanceUser) -> Response:
    """Downloadable error report: every row that was not imported, with the reason."""
    report = PaymentService(db).build_error_report(batch_id)
    return Response(
        content=report,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="import-errors-{str(batch_id)[:8]}.csv"'},
    )


@router.get("", response_model=Page[PaymentListItem])
def list_payments(
    db: DbSession,
    _user: FinanceUser,
    filters: Annotated[PaymentFilters, Query()],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    sort_by: SortField = "transaction_date",
    sort_dir: SortDir = "desc",
) -> Page[PaymentListItem]:
    return PaymentService(db).list_payments(filters, page=page, page_size=page_size, sort_by=sort_by, sort_dir=sort_dir)


@router.get("/{payment_id}", response_model=PaymentDetail)
def get_payment(payment_id: uuid.UUID, db: DbSession, _user: FinanceUser) -> PaymentDetail:
    return PaymentService(db).get_payment(payment_id)
