"""Guardrails applied to every AI-written answer (BRD FR-031).

The model may only PHRASE facts that the application retrieved. These checks reject an answer that
contains a number or an identifier (invoice / transaction reference) that is not in those facts, so the
model cannot invent an amount, a status or a record. When a check fails the caller uses the deterministic
answer instead.
"""

import re

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_IDENTIFIER = re.compile(r"\b(?:INV|TXN)-[A-Za-z0-9]+\b", re.IGNORECASE)
# "1. ", "2) ", "(3) " at the start of a line: a list marker is formatting, not a claimed number.
_LIST_MARKER = re.compile(r"(?m)^\s*\(?\d{1,2}[.)]\s+")


def _numbers(text: str) -> set[str]:
    """Canonical numeric tokens: thousands separators and trailing zeros removed (10,000.00 == 10000)."""
    found: set[str] = set()
    for token in _NUMBER.findall(text):
        token = token.replace(",", "").rstrip(".")
        if "." in token:
            token = token.rstrip("0").rstrip(".")
        found.add(token.lstrip("0") or "0")
    return found


def ungrounded_numbers(answer: str, facts: str) -> list[str]:
    """Numbers that appear in the answer but nowhere in the facts."""
    allowed = _numbers(facts)
    return sorted(n for n in _numbers(_LIST_MARKER.sub("", answer)) if n not in allowed)


def ungrounded_identifiers(answer: str, facts: str) -> list[str]:
    """INV-/TXN- references in the answer that are not in the facts."""
    allowed = {i.upper() for i in _IDENTIFIER.findall(facts)}
    return sorted({i.upper() for i in _IDENTIFIER.findall(answer)} - allowed)


def is_grounded(answer: str, facts: str) -> bool:
    return not ungrounded_numbers(answer, facts) and not ungrounded_identifiers(answer, facts)


# ---------------------------------------------------------------------------------------------
# Rewrite checks: the model may only REWORD a finished, deterministic draft.
# ---------------------------------------------------------------------------------------------

# Money-like numbers (12,500.00 / 9,999.99 / 1,000) and references are the facts that must survive a rewrite.
# Plain integers (counts, days, date parts) are not required, so a friendlier date is fine, but they still
# may not be INVENTED (see ungrounded_numbers).
_MONEY_LIKE = re.compile(r"\d[\d,]*\.\d+|\d{1,3}(?:,\d{3})+")


def missing_key_facts(answer: str, draft: str) -> list[str]:
    """References and money amounts present in the draft but dropped from the answer."""
    answer_numbers = _numbers(answer)
    answer_ids = {i.upper() for i in _IDENTIFIER.findall(answer)}
    missing = [i for i in {x.upper() for x in _IDENTIFIER.findall(draft)} if i not in answer_ids]
    missing += [n for n in _numbers(" ".join(_MONEY_LIKE.findall(draft))) if n not in answer_numbers]
    return sorted(missing)


def check_rewrite(answer: str, draft: str) -> list[str]:
    """Problems with an AI rewrite of `draft`. An empty list means acceptable.

    A rewrite fails if it adds a number or reference that the draft does not contain, or drops a reference or
    money amount that it does. This cannot catch every misstatement (a model could still pair valid figures
    wrongly), which is why the UI also shows the underlying records and labels the wording as AI-written.
    """
    problems = [f"added {n}" for n in ungrounded_numbers(answer, draft)]
    problems += [f"added {i}" for i in ungrounded_identifiers(answer, draft)]
    problems += [f"dropped {m}" for m in missing_key_facts(answer, draft)]
    return problems
