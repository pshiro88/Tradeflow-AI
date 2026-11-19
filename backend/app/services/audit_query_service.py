"""Read-only queries over the audit trail (Admin only). Logs are append-only; nothing here can change them."""

from datetime import UTC, datetime, time, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.audit import AIAuditLog, AuditLog
from app.models.user import User
from app.schemas.audit import (
    AIAuditFilters,
    AIAuditItem,
    AuditFilters,
    AuditLogItem,
    AuditOptions,
    UserOption,
)
from app.schemas.common import Page


def _bounds(date_from, date_to) -> tuple[datetime | None, datetime | None]:
    """Inclusive calendar dates (UTC) -> a half-open timestamp range."""
    start = datetime.combine(date_from, time.min, tzinfo=UTC) if date_from else None
    end = datetime.combine(date_to, time.min, tzinfo=UTC) + timedelta(days=1) if date_to else None
    return start, end


class AuditQueryService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def activity(self, f: AuditFilters, *, page: int, page_size: int) -> Page[AuditLogItem]:
        def apply(stmt: Select) -> Select:
            start, end = _bounds(f.date_from, f.date_to)
            if f.user_id:
                stmt = stmt.where(AuditLog.user_id == f.user_id)
            if f.action:
                stmt = stmt.where(AuditLog.action == f.action)
            if f.entity_type:
                stmt = stmt.where(AuditLog.entity_type == f.entity_type)
            if f.entity_id:
                stmt = stmt.where(AuditLog.entity_id == f.entity_id)
            if f.search:
                stmt = stmt.where(AuditLog.action.ilike(f"%{f.search.strip()}%"))
            if start:
                stmt = stmt.where(AuditLog.created_at >= start)
            if end:
                stmt = stmt.where(AuditLog.created_at < end)
            return stmt

        total = self.db.scalar(select(func.count()).select_from(apply(select(AuditLog.id)).subquery())) or 0
        rows = self.db.execute(
            apply(select(AuditLog, User.full_name).outerjoin(User, User.id == AuditLog.user_id))
            .order_by(AuditLog.created_at.desc(), AuditLog.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        items = [
            AuditLogItem(
                id=log.id, created_at=log.created_at, user_id=log.user_id, user_name=name, action=log.action,
                entity_type=log.entity_type, entity_id=log.entity_id, old_values=log.old_values, new_values=log.new_values,
            )
            for log, name in rows
        ]
        return Page.build(items, total, page, page_size)

    def ai_requests(self, f: AIAuditFilters, *, page: int, page_size: int) -> Page[AIAuditItem]:
        def apply(stmt: Select) -> Select:
            start, end = _bounds(f.date_from, f.date_to)
            if f.user_id:
                stmt = stmt.where(AIAuditLog.user_id == f.user_id)
            if f.operation:
                stmt = stmt.where(AIAuditLog.operation_type == f.operation)
            if f.status:
                stmt = stmt.where(AIAuditLog.status == f.status)
            if f.search:
                stmt = stmt.where(AIAuditLog.request_summary.ilike(f"%{f.search.strip()}%"))
            if start:
                stmt = stmt.where(AIAuditLog.created_at >= start)
            if end:
                stmt = stmt.where(AIAuditLog.created_at < end)
            return stmt

        total = self.db.scalar(select(func.count()).select_from(apply(select(AIAuditLog.id)).subquery())) or 0
        rows = self.db.execute(
            apply(select(AIAuditLog, User.full_name).outerjoin(User, User.id == AIAuditLog.user_id))
            .order_by(AIAuditLog.created_at.desc(), AIAuditLog.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        items = [
            AIAuditItem(
                id=log.id, created_at=log.created_at, user_id=log.user_id, user_name=name, operation_type=log.operation_type,
                model_name=log.model_name, request_summary=log.request_summary, response_summary=log.response_summary,
                status=log.status, duration_ms=log.duration_ms, details=log.details,
            )
            for log, name in rows
        ]
        return Page.build(items, total, page, page_size)

    def options(self) -> AuditOptions:
        names = lambda col: sorted(v for (v,) in self.db.execute(select(col).distinct()).all() if v)  # noqa: E731
        users = self.db.execute(select(User.id, User.full_name).order_by(User.full_name)).all()
        return AuditOptions(
            users=[UserOption(id=i, name=n) for i, n in users],
            actions=names(AuditLog.action),
            entity_types=names(AuditLog.entity_type),
            ai_operations=names(AIAuditLog.operation_type),
            ai_statuses=names(AIAuditLog.status),
        )
