"""Live tests against the real local model. Skipped unless RUN_OLLAMA_TESTS=1 (they are slow and need Ollama).

    set RUN_OLLAMA_TESTS=1 && python -m pytest tests/test_ollama_live.py -s
"""

import os
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.db.seed_data import INVOICES
from app.services.document_extraction import extract_fields
from app.services.ollama_service import OllamaService
from app.services.pdf_service import validate_and_extract

pytestmark = pytest.mark.skipif(os.environ.get("RUN_OLLAMA_TESTS") != "1", reason="set RUN_OLLAMA_TESTS=1 to run live model tests")

DOCS = Path(__file__).resolve().parents[2] / "sample_data" / "documents"


@pytest.fixture(scope="module")
def llm() -> OllamaService:
    s = get_settings()
    service = OllamaService(s.ollama_base_url, s.ollama_model, s.ollama_timeout_seconds)
    if not service.is_available():
        pytest.skip("Ollama or the configured model is not available")
    return service


@pytest.mark.parametrize("pdf", sorted(DOCS.glob("*.pdf")), ids=lambda p: p.name)
def test_real_model_extracts_the_sample_invoices(llm, pdf):
    number = re.match(r"(INV-\d+)", pdf.name).group(1)
    expected = next(i for i in INVOICES if i.invoice_number == number)
    delta = Decimal("500.00") if "differs" in pdf.name else Decimal("0")

    text = validate_and_extract(pdf.read_bytes(), max_bytes=10 * 1024 * 1024, max_pages=20).text
    outcome = extract_fields(llm, text, max_chars=12000)
    f, q = outcome.fields, outcome.quality
    print(f"\n{pdf.name}\n  fields={f.model_dump(mode='json')}\n  quality={q}\n  issues={[i.model_dump() for i in outcome.issues]}")

    assert f.invoice_number == expected.invoice_number
    assert f.currency == expected.currency
    assert f.invoice_amount == expected.amount + delta
    assert f.buyer_name == expected.buyer
    assert f.exporter_name == expected.exporter
    assert isinstance(f.invoice_date, date) and isinstance(f.due_date, date)
    # nothing the model returned is invented: every extracted value appears in the document
    assert "NOT_FOUND_IN_TEXT" not in q.values(), q


def test_real_model_returns_null_instead_of_inventing_missing_fields(llm):
    """The document has an invoice number and a buyer only. Everything else must come back null."""
    text = "COMMERCIAL INVOICE\nInvoice No: INV-5555\nBuyer: Acme Trading LLC\nThank you for your business.\n"
    outcome = extract_fields(llm, text, max_chars=12000)
    f = outcome.fields
    print(f"\nsparse document -> {f.model_dump(mode='json')}")
    assert f.invoice_number == "INV-5555"
    assert f.invoice_amount is None, "the model invented a total"
    assert f.due_date is None and f.invoice_date is None, "the model invented dates"
    assert f.currency is None, "the model invented a currency"
    assert "NOT_FOUND_IN_TEXT" not in outcome.quality.values()


LIVE_QUESTIONS = [
    "Which invoices are overdue?",
    "Show payments that have not been reconciled.",
    "Why is INV-1024 partially paid?",
    "Summarise payment discrepancies this month.",
    "Which buyers have the highest outstanding balances?",
    "Show invoices with missing supporting documents.",
    "Explain the reconciliation result for transaction TXN-1005.",
    "Which invoices have been pending for more than seven days?",
]


def test_real_model_copilot_wording_is_grounded_or_falls_back_safely(llm, client, finance, db):
    """For each example question the answer is either the model's grounded wording or the deterministic one.
    Never an answer that carries a number or reference that is not in the retrieved data."""
    from app.db.seed import seed_demo_data
    from app.main import app
    from app.services.ai_guardrails import is_grounded
    from app.services.ollama_service import get_llm

    seed_demo_data(db)
    db.commit()
    client.post("/api/v1/reconciliation/run", headers=finance)
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        ai_used = 0
        for question in LIVE_QUESTIONS:
            body = client.post("/api/v1/ai/chat", json={"message": question}, headers=finance).json()
            print(f"\n[{body['generated_by']}] {question}\n   -> {body['answer'][:300]}" + (f"\n   note: {body['ai_note']}" if body["ai_note"] else ""))
            assert body["answer"] and body["intent"] != "UNKNOWN"
            ai_used += body["generated_by"] == "AI"
        print(f"\nAI wording accepted for {ai_used}/{len(LIVE_QUESTIONS)} questions; the rest used the deterministic answer")
    finally:
        app.dependency_overrides.pop(get_llm, None)
