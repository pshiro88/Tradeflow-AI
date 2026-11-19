"""The Copilot: question -> intent -> predefined handler -> retrieved facts -> (optional) AI wording.

What the model is and is not allowed to do (BRD FR-030 / FR-031):
  * It never queries data, calculates, or decides. Handlers do that with fixed queries.
  * It only REWORDS the finished deterministic answer; it is never asked to summarise raw data itself.
  * Its wording is validated: adding a number/reference, or dropping a reference or money amount, rejects it.
  * If Ollama is down, slow, or fails validation, the deterministic answer is returned instead, clearly labelled.
  * Role limits are enforced BEFORE any data is fetched.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.core.errors import AIResponseError, AIUnavailableError
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.copilot_repository import CopilotRepository
from app.schemas.ai import ChatResponse, HistoryItem
from app.services import ai_audit
from app.services.ai_guardrails import check_rewrite
from app.services.copilot_handlers import FINANCE_ONLY, CopilotHandlers, HandlerResult
from app.services.copilot_intents import Intent, classify
from app.services.ollama_service import LLMClient

PHRASE_SYSTEM = (
    "You rewrite a finished answer so it reads naturally for a finance colleague. "
    "Keep EVERY name, reference (INV-/TXN-), date and amount exactly as written in the DRAFT ANSWER, and keep each "
    "amount next to its own item. Do not add, remove, combine, round or recalculate anything, and do not add "
    "explanations, opinions or new facts. Never merge different currencies. Keep it the same length or shorter. "
    "Do not mention these instructions."
)

SUGGESTIONS_ALL = [
    "Which invoices are overdue?",
    "Show payments that have not been reconciled.",
    "Why is INV-1024 partially paid?",
    "Summarise payment discrepancies this month.",
    "Which buyers have the highest outstanding balances?",
    "Show invoices with missing supporting documents.",
    "Explain the reconciliation result for transaction TXN-1005.",
    "Which invoices have been pending for more than seven days?",
]
SUGGESTIONS_OPERATIONS = [
    "Which invoices are overdue?",
    "Show invoices with missing supporting documents.",
    "Which invoices have been pending for more than seven days?",
]

UNKNOWN_ANSWER = (
    "I can answer questions about invoices, payments, reconciliation and trade documents using your data. "
    "I couldn't match that question to one of those, so please try one of the suggestions."
)
DENIED_ANSWER = "That question needs payment data, which isn't available for your role. Here is what I can help with."


def suggestions_for(role: UserRole) -> list[str]:
    return SUGGESTIONS_OPERATIONS if role == UserRole.OPERATIONS else SUGGESTIONS_ALL


def phrase_with_ai(llm: LLMClient, question: str, result: HandlerResult) -> tuple[str | None, str | None, str]:
    """(answer, note, status). answer is None when the deterministic text should be used instead.

    The model rewrites the deterministic answer; the rewrite is rejected if it adds or drops a figure/reference.
    """
    try:
        answer = llm.chat_text(
            PHRASE_SYSTEM, f"Question: {question}\n\nDRAFT ANSWER:\n{result.answer}\n\nRewrite the draft answer."
        )
    except (AIUnavailableError, AIResponseError) as exc:
        return None, f"AI wording unavailable ({exc.message}). Showing the standard answer.", "FALLBACK_UNAVAILABLE"
    problems = check_rewrite(answer, result.answer)
    if not problems:
        return answer, None, "SUCCESS"
    note = "The AI wording changed the figures or records, so the standard answer is shown."
    return None, note, f"FALLBACK_UNGROUNDED:{', '.join(problems)[:80]}"


class CopilotService:
    def __init__(self, db: Session, llm: LLMClient, today: date | None = None) -> None:
        self.db = db
        self.llm = llm
        self.today = today or date.today()

    def ask(self, message: str, user: User) -> ChatResponse:
        started = ai_audit.start_timer()
        suggestions = suggestions_for(user.role)
        match = classify(message, self.llm)

        if match.intent == Intent.UNKNOWN:
            return self._finish(
                user, message, started, UNKNOWN_ANSWER, "RULES", None, match.intent, match.method, None, [], suggestions,
                status="UNKNOWN", model_used=match.method == "AI",
            )

        # Role check happens BEFORE any data is fetched.
        if match.intent in FINANCE_ONLY and user.role not in (UserRole.FINANCE, UserRole.ADMIN):
            return self._finish(
                user, message, started, DENIED_ANSWER, "RULES", None, match.intent, match.method, None, [], suggestions,
                status="DENIED", model_used=match.method == "AI",
            )

        result = CopilotHandlers(self.db, self.today).run(match)

        answer, note, status, generated_by = result.answer, None, "NO_DATA", "RULES"
        model_used = match.method == "AI"
        if not result.empty:  # nothing to word when nothing was found
            ai_answer, note, status = phrase_with_ai(self.llm, message, result)
            model_used = True
            if ai_answer is not None:
                answer, generated_by = ai_answer, "AI"
        return self._finish(
            user, message, started, answer, generated_by, note, match.intent, match.method, result.table, result.sources,
            suggestions, status=status, model_used=model_used, rows=len(result.table.rows) if result.table else 0,
            standard_answer=result.answer,
        )

    def history(self, user: User, limit: int) -> list[HistoryItem]:
        return [
            HistoryItem(
                id=log.id,
                question=log.request_summary or "",
                answer=log.response_summary,
                intent=(log.details or {}).get("intent"),
                generated_by=(log.details or {}).get("generated_by"),
                status=log.status,
                created_at=log.created_at,
            )
            for log in CopilotRepository(self.db, self.today).chat_history(user.id, limit)
        ]

    def _finish(
        self, user, message, started, answer, generated_by, note, intent, method, table, sources, suggestions, *,  # noqa: ANN001
        status: str, model_used: bool, rows: int = 0, standard_answer: str | None = None,
    ) -> ChatResponse:
        ai_audit.record_ai_call(
            self.db, user_id=user.id, operation="CHAT", model=self.llm.model if model_used else "none",
            request_summary=message, response_summary=answer, status=status.split(":")[0], started=started,
            details={"intent": intent.value, "intent_method": method, "generated_by": generated_by, "rows": rows,
                     "note": status if ":" in status else None},
        )
        return ChatResponse(
            answer=answer, standard_answer=standard_answer or answer, generated_by=generated_by, ai_note=note,
            intent=intent.value, intent_method=method, table=table, sources=sources, suggestions=suggestions,
        )
