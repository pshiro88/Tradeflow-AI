import uuid
from typing import Any

from pydantic_core import to_jsonable_python
from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def record_audit(
    db: Session,
    *,
    user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    old_values: dict[str, Any] | None = None,
    new_values: dict[str, Any] | None = None,
) -> AuditLog:
    """Append an audit row inside the caller's transaction (commits or rolls back with the change itself).

    Decimals, dates and UUIDs are converted to JSON-safe values; money is stored as strings, never floats.
    """
    entry = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_values=to_jsonable_python(old_values) if old_values is not None else None,
        new_values=to_jsonable_python(new_values) if new_values is not None else None,
    )
    db.add(entry)
    db.flush()
    return entry
