from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, DbSession, require_role
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.ai import (
    AIStatus,
    ChatRequest,
    ChatResponse,
    DiscrepancyExplanation,
    ExplainDiscrepancyRequest,
    HistoryItem,
)
from app.services.copilot_service import CopilotService, suggestions_for
from app.services.discrepancy_service import explain_discrepancy
from app.services.ollama_service import LLMClient, get_llm

router = APIRouter(prefix="/ai", tags=["ai"])

Llm = Annotated[LLMClient, Depends(get_llm)]
FinanceUser = Annotated[User, Depends(require_role(UserRole.FINANCE))]


@router.get("/status", response_model=AIStatus)
def ai_status(_user: CurrentUser, llm: Llm) -> AIStatus:
    """Is the local model reachable? Lets the UI explain a slow or fallback answer."""
    return AIStatus(available=llm.is_available(), model=llm.model)


@router.get("/suggestions", response_model=list[str])
def suggestions(user: CurrentUser) -> list[str]:
    """Example questions this role can ask."""
    return suggestions_for(user.role)


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: DbSession, user: CurrentUser, llm: Llm) -> ChatResponse:
    """Ask a question about operations data. Answers come from predefined queries; the AI only words them."""
    return CopilotService(db, llm).ask(payload.message, user)


@router.get("/history", response_model=list[HistoryItem])
def history(
    db: DbSession, user: CurrentUser, llm: Llm, limit: Annotated[int, Query(ge=1, le=100)] = 30
) -> list[HistoryItem]:
    """The signed-in user's own recent questions (never anyone else's)."""
    return CopilotService(db, llm).history(user, limit)


@router.post("/explain-discrepancy", response_model=DiscrepancyExplanation)
def explain(payload: ExplainDiscrepancyRequest, db: DbSession, user: FinanceUser, llm: Llm) -> DiscrepancyExplanation:
    """Plain-language explanation of a reconciliation result. The AI explains; it never allocates."""
    return explain_discrepancy(db, llm, user, payload.reconciliation_id)
