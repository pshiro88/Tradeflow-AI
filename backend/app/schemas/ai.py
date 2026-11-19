import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

Message = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
GeneratedBy = Literal["AI", "RULES"]


class SourceRef(BaseModel):
    """A record the answer is based on, so the reader can open it."""

    type: Literal["invoice", "payment", "reconciliation", "document"]
    label: str
    path: str


class TableColumn(BaseModel):
    key: str
    label: str
    align: Literal["left", "right"] = "left"


class AnswerTable(BaseModel):
    """The retrieved data behind an answer. Always shown, so a person can check the model's wording."""

    title: str
    columns: list[TableColumn]
    rows: list[dict[str, str]]


class ChatRequest(BaseModel):
    message: Message


class ChatResponse(BaseModel):
    answer: str
    standard_answer: str  # the deterministic wording, always provided so the AI's version can be compared
    generated_by: GeneratedBy  # "AI" = wording written by the local model from retrieved data; "RULES" = fixed text
    ai_note: str | None
    intent: str
    intent_method: str
    table: AnswerTable | None
    sources: list[SourceRef]
    suggestions: list[str]


class HistoryItem(BaseModel):
    id: uuid.UUID
    question: str
    answer: str | None
    intent: str | None
    generated_by: str | None
    status: str
    created_at: datetime


class AIStatus(BaseModel):
    available: bool
    model: str


class ExplainDiscrepancyRequest(BaseModel):
    reconciliation_id: uuid.UUID


class DiscrepancyExplanation(BaseModel):
    status: str
    explanation: str
    generated_by: GeneratedBy
    ai_note: str | None
    rule_explanation: str  # the deterministic engine's own wording, always provided
    next_step: str
