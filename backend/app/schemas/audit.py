import uuid
from datetime import date, datetime
from typing import Any, Self

from pydantic import BaseModel, model_validator


class _DateRange(BaseModel):
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from cannot be after date_to")
        return self


class AuditFilters(_DateRange):
    user_id: uuid.UUID | None = None
    action: str | None = None
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    search: str | None = None  # matches the action name


class AIAuditFilters(_DateRange):
    user_id: uuid.UUID | None = None
    operation: str | None = None
    status: str | None = None
    search: str | None = None  # matches the request text


class AuditLogItem(BaseModel):
    id: uuid.UUID
    created_at: datetime
    user_id: uuid.UUID | None
    user_name: str | None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    old_values: dict[str, Any] | None
    new_values: dict[str, Any] | None


class AIAuditItem(BaseModel):
    id: uuid.UUID
    created_at: datetime
    user_id: uuid.UUID | None
    user_name: str | None
    operation_type: str
    model_name: str
    request_summary: str | None
    response_summary: str | None
    status: str
    duration_ms: int | None
    details: dict[str, Any] | None


class UserOption(BaseModel):
    id: uuid.UUID
    name: str


class AuditOptions(BaseModel):
    users: list[UserOption]
    actions: list[str]
    entity_types: list[str]
    ai_operations: list[str]
    ai_statuses: list[str]
