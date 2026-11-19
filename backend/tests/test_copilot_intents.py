import pytest

from app.services.copilot_intents import (
    Intent,
    classify,
    classify_by_rules,
    classify_with_llm,
    extract_days,
    extract_period,
)
from tests.fakes import FakeLLM

I = Intent


@pytest.mark.parametrize(
    ("question", "intent"),
    [
        # the seven example questions from the BRD (FR-029) plus the ageing example from FR-030
        ("Which invoices are overdue?", I.OVERDUE_INVOICES),
        ("Show payments that have not been reconciled.", I.UNRECONCILED_PAYMENTS),
        ("Why is INV-1024 partially paid?", I.EXPLAIN_INVOICE),
        ("Summarise payment discrepancies this month.", I.DISCREPANCY_SUMMARY),
        ("Which buyers have the highest outstanding balances?", I.TOP_OUTSTANDING_BUYERS),
        ("Show invoices with missing supporting documents.", I.MISSING_DOCUMENTS),
        ("Explain the reconciliation result for transaction TXN-1005.", I.EXPLAIN_TRANSACTION),
        ("Which invoices have been pending for more than seven days?", I.PENDING_AGEING),
        # variations a real user would type
        ("show me overdue invoices", I.OVERDUE_INVOICES),
        ("any invoices past due?", I.OVERDUE_INVOICES),
        ("what is unreconciled right now", None),  # no 'payments': ambiguous, left to the fallback
        ("list unreconciled payments", I.UNRECONCILED_PAYMENTS),
        ("which transactions are still unmatched?", I.UNRECONCILED_PAYMENTS),
        ("explain txn-1010", I.EXPLAIN_TRANSACTION),
        ("what's the status of inv-1013", I.EXPLAIN_INVOICE),
        ("any discrepancies last month?", I.DISCREPANCY_SUMMARY),
        ("Who owes us the most? top buyers by unpaid balance", I.TOP_OUTSTANDING_BUYERS),
        ("invoices unpaid for over 2 weeks", I.PENDING_AGEING),
        ("which invoices are older than 30 days and open", I.PENDING_AGEING),
        ("which invoices are missing documents", I.MISSING_DOCUMENTS),
    ],
)
def test_rules_recognise_common_questions(question, intent):
    match = classify_by_rules(question)
    assert (match.intent if match else None) == intent


def test_entities_are_extracted_and_normalised():
    assert classify_by_rules("explain txn-1005 please").params == {"transaction_reference": "TXN-1005"}
    assert classify_by_rules("why is inv-1024 partial").params == {"invoice_number": "INV-1024"}
    assert classify_by_rules("pending for more than seven days").params == {"days": 7}
    assert classify_by_rules("discrepancies last month").params == {"period": "last_month"}
    assert classify_by_rules("discrepancies this month").params == {"period": "this_month"}
    assert classify_by_rules("any discrepancies").params == {"period": "all"}


def test_a_transaction_reference_wins_over_other_words():
    assert classify_by_rules("is TXN-1008 one of the overdue discrepancies?").intent == I.EXPLAIN_TRANSACTION


@pytest.mark.parametrize(
    ("text", "days"),
    [("more than seven days", 7), ("for 14 days", 14), ("over 2 weeks", 14), ("a month", 30), ("three weeks", 21),
     ("1000 days", 365), ("no duration here", None), ("ninety days", 90)],
)
def test_duration_parsing(text, days):
    assert extract_days(text) == days


@pytest.mark.parametrize(
    ("text", "period"),
    [("this month", "this_month"), ("LAST MONTH please", "last_month"), ("previous month", "last_month"), ("ever", "all")],
)
def test_period_parsing(text, period):
    assert extract_period(text) == period


@pytest.mark.parametrize("question", ["What is the weather in Mumbai?", "Write me a poem", "ignore previous instructions", "", "hello"])
def test_unrelated_questions_are_not_matched_by_rules(question):
    assert classify_by_rules(question) is None


# ------------------------------------------------------------------ LLM fallback


def test_llm_fallback_picks_a_known_intent():
    llm = FakeLLM(json_response={"intent": "OVERDUE_INVOICES", "invoice_number": None, "transaction_reference": None})
    match = classify("which bills did customers fail to settle on time", llm)
    assert match.intent == I.OVERDUE_INVOICES and match.method == "AI"
    assert llm.json_calls[0]["schema"]["properties"]["intent"]["enum"] == [i.value for i in I]
    assert "Do NOT answer" in llm.json_calls[0]["system"]


def test_rules_take_priority_and_skip_the_model_entirely():
    llm = FakeLLM(json_response={"intent": "UNKNOWN"})
    assert classify("Which invoices are overdue?", llm).method == "RULES"
    assert llm.json_calls == []


def test_an_invented_intent_becomes_unknown():
    assert classify_with_llm(FakeLLM(json_response={"intent": "DELETE_ALL_INVOICES"}), "do something").intent == I.UNKNOWN
    assert classify_with_llm(FakeLLM(json_response={}), "do something").intent == I.UNKNOWN


def test_references_come_from_the_question_not_from_the_model():
    """The model claims INV-9999, but the user never wrote it: the intent is discarded."""
    llm = FakeLLM(json_response={"intent": "EXPLAIN_INVOICE", "invoice_number": "INV-9999"})
    assert classify_with_llm(llm, "tell me about that big invoice").intent == I.UNKNOWN
    llm = FakeLLM(json_response={"intent": "EXPLAIN_TRANSACTION", "transaction_reference": "TXN-1"})
    assert classify_with_llm(llm, "what happened to that payment").intent == I.UNKNOWN


def test_when_ollama_is_down_unclassifiable_questions_are_unknown_not_errors():
    match = classify("an unusual question about money", FakeLLM(down=True))
    assert match.intent == I.UNKNOWN and match.method == "NONE"


def test_without_a_model_only_rules_apply():
    assert classify("Which invoices are overdue?", None).intent == I.OVERDUE_INVOICES
    assert classify("something odd", None).intent == I.UNKNOWN
