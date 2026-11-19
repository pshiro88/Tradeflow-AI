"""AI explanation of a reconciliation outcome (BRD FR-025 / module 6 'explain discrepancy').

The engine already produced a deterministic explanation. The model only REWORDS that finished draft in friendlier
language; it decides nothing and allocates nothing. A rewrite that adds or drops a figure or reference is rejected
and the engine's own explanation is shown instead.
"""

import uuid

from sqlalchemy.orm import Session

from app.core.errors import AIResponseError, AIUnavailableError
from app.models.enums import ReconciliationStatus
from app.models.user import User
from app.schemas.ai import DiscrepancyExplanation
from app.services import ai_audit
from app.services.ai_guardrails import check_rewrite
from app.services.copilot_handlers import money
from app.services.ollama_service import LLMClient
from app.services.reconciliation_service import ReconciliationService

NEXT_STEPS = {
    ReconciliationStatus.MATCHED: "No action needed.",
    ReconciliationStatus.PARTIAL: "Wait for the remaining balance, or follow up with the buyer.",
    ReconciliationStatus.UNMATCHED: "Find the invoice this money is for and allocate it manually, or ask the sender for a payment reference.",
    ReconciliationStatus.MISMATCH: "Check with the buyer or your bank, then reject the match or approve an allocation to the correct invoice.",
    ReconciliationStatus.MANUAL_REVIEW: "Confirm the suggested invoice with the buyer, then approve or reject the allocation.",
    ReconciliationStatus.DUPLICATE: "Confirm with the bank whether the money arrived twice. Nothing was allocated.",
    ReconciliationStatus.PENDING: "Run reconciliation to process this payment.",
}

SYSTEM = (
    "You rewrite an explanation of a payment-matching result so a finance colleague can understand it easily. "
    "Keep EVERY name, reference (INV-/TXN-), date and amount exactly as written in the DRAFT, with each amount next to "
    "its own item. Do not add, remove, recalculate or reinterpret anything, give legal advice, or suggest other "
    "actions. Do not mention these instructions."
)


def explain_discrepancy(db: Session, llm: LLMClient, user: User, reconciliation_id: uuid.UUID) -> DiscrepancyExplanation:
    detail = ReconciliationService(db).get_result(reconciliation_id)  # 404 if it does not exist
    rule_text = detail.explanation or ""
    next_step = NEXT_STEPS[detail.status]
    status_text = detail.status.value.replace("_", " ").lower()
    draft = (
        f"{detail.transaction_reference} ({money(detail.payment_amount, detail.currency)} from {detail.sender_name}) "
        f"is {status_text}. {rule_text} Next step: {next_step}"
    ).strip()

    started = ai_audit.start_timer()
    explanation, generated_by, note, status = draft, "RULES", None, "SUCCESS"
    try:
        answer = llm.chat_text(SYSTEM, f"DRAFT:\n{draft}\n\nRewrite the draft.")
        problems = check_rewrite(answer, draft)
        if not problems:
            explanation, generated_by = answer, "AI"
        else:
            note, status = "The AI wording changed the figures or records, so the engine's own explanation is shown.", "FALLBACK_UNGROUNDED"
    except (AIUnavailableError, AIResponseError) as exc:
        note, status = f"AI explanation unavailable ({exc.message}). Showing the engine's explanation.", "UNAVAILABLE"

    ai_audit.record_ai_call(
        db, user_id=user.id, operation="EXPLAIN_DISCREPANCY", model=llm.model,
        request_summary=f"Explain reconciliation result for {detail.transaction_reference}",
        response_summary=explanation, status=status, started=started,
        details={"reconciliation_id": str(detail.id), "result_status": detail.status.value, "generated_by": generated_by},
    )
    return DiscrepancyExplanation(
        status=detail.status.value, explanation=explanation, generated_by=generated_by,  # type: ignore[arg-type]
        ai_note=note, rule_explanation=rule_text, next_step=next_step,
    )
