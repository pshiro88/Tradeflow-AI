"""Understanding what the user is asking (BRD FR-030 step 1: "Identify the intent").

Rules come first: they are deterministic, instant, testable and need no model. Only a question the rules
cannot place goes to the LLM, and then only to PICK ONE OF THE KNOWN INTENTS. The model never writes a
query, never chooses a table and never sees the database. Whatever it returns is validated: an unknown
intent or a reference that is not in the question is discarded.
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.core.errors import AIResponseError, AIUnavailableError
from app.services.ollama_service import LLMClient


class Intent(StrEnum):
    OVERDUE_INVOICES = "OVERDUE_INVOICES"
    PENDING_AGEING = "PENDING_AGEING"
    UNRECONCILED_PAYMENTS = "UNRECONCILED_PAYMENTS"
    DISCREPANCY_SUMMARY = "DISCREPANCY_SUMMARY"
    TOP_OUTSTANDING_BUYERS = "TOP_OUTSTANDING_BUYERS"
    MISSING_DOCUMENTS = "MISSING_DOCUMENTS"
    EXPLAIN_INVOICE = "EXPLAIN_INVOICE"
    EXPLAIN_TRANSACTION = "EXPLAIN_TRANSACTION"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class IntentMatch:
    intent: Intent
    params: dict[str, Any] = field(default_factory=dict)
    method: str = "RULES"  # RULES | AI | NONE


_INVOICE_REF = re.compile(r"\bINV-[A-Za-z0-9]+\b", re.IGNORECASE)
_TXN_REF = re.compile(r"\bTXN-[A-Za-z0-9]+\b", re.IGNORECASE)

_NUMBER_WORDS = {
    "a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "fourteen": 14, "fifteen": 15, "twenty": 20, "thirty": 30,
    "sixty": 60, "ninety": 90,
}
_UNIT_DAYS = {"day": 1, "days": 1, "week": 7, "weeks": 7, "month": 30, "months": 30}
_DURATION = re.compile(r"\b(\d{1,5}|" + "|".join(_NUMBER_WORDS) + r")\s*(days?|weeks?|months?)\b", re.IGNORECASE)

MAX_DAYS = 365


def extract_days(message: str) -> int | None:
    """'more than seven days' -> 7, '2 weeks' -> 14, 'a month' -> 30."""
    match = _DURATION.search(message)
    if not match:
        return None
    amount_text, unit = match.group(1).lower(), match.group(2).lower()
    amount = int(amount_text) if amount_text.isdigit() else _NUMBER_WORDS[amount_text]
    return min(amount * _UNIT_DAYS[unit], MAX_DAYS)


def extract_period(message: str) -> str:
    lowered = message.lower()
    if "last month" in lowered or "previous month" in lowered:
        return "last_month"
    if "this month" in lowered or "current month" in lowered:
        return "this_month"
    return "all"


def _has(message: str, *patterns: str) -> bool:
    return any(re.search(p, message, re.IGNORECASE) for p in patterns)


def classify_by_rules(message: str) -> IntentMatch | None:
    """Return the intent if a rule recognises the question, otherwise None."""
    txn = _TXN_REF.search(message)
    if txn:
        return IntentMatch(Intent.EXPLAIN_TRANSACTION, {"transaction_reference": txn.group(0).upper()})

    inv = _INVOICE_REF.search(message)
    if inv:
        return IntentMatch(Intent.EXPLAIN_INVOICE, {"invoice_number": inv.group(0).upper()})

    if _has(message, r"discrepanc", r"\bmismatch", r"\bexceptions?\b"):
        return IntentMatch(Intent.DISCREPANCY_SUMMARY, {"period": extract_period(message)})

    if _has(message, r"\b(buyers?|customers?|clients?)\b") and _has(message, r"\b(highest|largest|biggest|most|top|greatest)\b") and _has(
        message, r"outstanding", r"\bowe", r"balance", r"unpaid"
    ):
        return IntentMatch(Intent.TOP_OUTSTANDING_BUYERS)

    days = extract_days(message)
    if days is not None and _has(message, r"pending", r"outstanding", r"unpaid", r"\bopen\b", r"ageing", r"aging", r"older than"):
        return IntentMatch(Intent.PENDING_AGEING, {"days": days})

    if _has(message, r"overdue", r"past due", r"\blate\b") and not _has(message, r"\bpayments?\b.*\boverdue\b"):
        return IntentMatch(Intent.OVERDUE_INVOICES)

    if _has(message, r"\b(un)?reconciled\b", r"not\s+(?:yet\s+)?(?:been\s+)?reconciled", r"unmatched", r"\bunreconciled\b") and _has(
        message, r"payments?", r"transactions?"
    ):
        return IntentMatch(Intent.UNRECONCILED_PAYMENTS)

    if _has(message, r"missing") and _has(message, r"document", r"paperwork", r"supporting"):
        return IntentMatch(Intent.MISSING_DOCUMENTS)
    return None


# ---------------------------------------------------------------- LLM fallback (classification only)

CLASSIFY_SYSTEM = (
    "You route questions for a trade-finance operations tool. Choose the single best intent for the user's "
    "question from the allowed list, or UNKNOWN if none fits. Do NOT answer the question. "
    "Only fill invoice_number / transaction_reference if that exact reference appears in the question."
)


def classify_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": [i.value for i in Intent]},
            "invoice_number": {"type": ["string", "null"]},
            "transaction_reference": {"type": ["string", "null"]},
        },
        "required": ["intent"],
    }


def classify_with_llm(llm: LLMClient, message: str) -> IntentMatch:
    """Ask the model to pick an intent. The answer is validated; anything unusable becomes UNKNOWN."""
    try:
        raw = llm.chat_json(CLASSIFY_SYSTEM, f"Question: {message}", classify_schema())
    except (AIUnavailableError, AIResponseError):
        return IntentMatch(Intent.UNKNOWN, method="NONE")

    try:
        intent = Intent(raw.get("intent"))
    except ValueError:
        return IntentMatch(Intent.UNKNOWN, method="AI")

    params: dict[str, Any] = {}
    if intent == Intent.EXPLAIN_INVOICE:
        ref = _INVOICE_REF.search(message)  # take the reference from the question itself, never from the model
        if not ref:
            return IntentMatch(Intent.UNKNOWN, method="AI")
        params["invoice_number"] = ref.group(0).upper()
    elif intent == Intent.EXPLAIN_TRANSACTION:
        ref = _TXN_REF.search(message)
        if not ref:
            return IntentMatch(Intent.UNKNOWN, method="AI")
        params["transaction_reference"] = ref.group(0).upper()
    elif intent == Intent.PENDING_AGEING:
        params["days"] = extract_days(message) or 7
    elif intent == Intent.DISCREPANCY_SUMMARY:
        params["period"] = extract_period(message)
    return IntentMatch(intent, params, method="AI")


def classify(message: str, llm: LLMClient | None) -> IntentMatch:
    matched = classify_by_rules(message)
    if matched is not None:
        return matched
    if llm is None:
        return IntentMatch(Intent.UNKNOWN, method="NONE")
    return classify_with_llm(llm, message)
