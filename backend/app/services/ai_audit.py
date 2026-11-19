import time
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AIAuditLog

MAX_REQUEST_CHARS = 500
MAX_RESPONSE_CHARS = 2000


def start_timer() -> float:
    return time.perf_counter()


def record_ai_call(
    db: Session,
    *,
    user_id: uuid.UUID | None,
    operation: str,
    model: str,
    request_summary: str,
    response_summary: str | None,
    status: str,
    started: float,
    details: dict[str, Any] | None = None,
) -> AIAuditLog:
    """Persist one LLM interaction (BRD FR-031: maintain AI request logs).

    Committed on its own so a failed or rolled-back business operation still leaves an audit trail.
    Only short summaries are stored: never full document text.
    """
    entry = AIAuditLog(
        user_id=user_id,
        operation_type=operation,
        model_name=model,
        request_summary=request_summary[:MAX_REQUEST_CHARS],
        response_summary=response_summary[:MAX_RESPONSE_CHARS] if response_summary is not None else None,
        status=status,
        duration_ms=int((time.perf_counter() - started) * 1000),
        details=details,
    )
    db.add(entry)
    db.commit()
    return entry
