"""Test doubles for the LLM and helpers to build PDFs. No live Ollama is needed for the test suite."""

from collections.abc import Callable
from typing import Any

import pymupdf

from app.core.errors import AIUnavailableError


class FakeLLM:
    """Scripted stand-in for OllamaService.

    json_response / text_response may be a value, or a callable (system, user, schema) -> value for
    tests that need to react to the prompt. Set `down=True` to simulate Ollama being unreachable.
    """

    model = "fake-model"

    def __init__(
        self,
        json_response: dict[str, Any] | Callable[..., dict[str, Any]] | None = None,
        text_response: str | Callable[..., str] | None = None,
        down: bool = False,
    ) -> None:
        self.json_response = json_response
        self.text_response = text_response
        self.down = down
        self.json_calls: list[dict[str, Any]] = []
        self.text_calls: list[dict[str, str]] = []

    def chat_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.json_calls.append({"system": system, "user": user, "schema": schema})
        if self.down:
            raise AIUnavailableError("The local AI service (Ollama) is not reachable. Is it running?")
        response = self.json_response(system, user, schema) if callable(self.json_response) else self.json_response
        if response is None:
            raise AssertionError("FakeLLM.chat_json called but no json_response was scripted")
        return response

    def chat_text(self, system: str, user: str) -> str:
        self.text_calls.append({"system": system, "user": user})
        if self.down:
            raise AIUnavailableError("The local AI service (Ollama) is not reachable. Is it running?")
        response = self.text_response(system, user) if callable(self.text_response) else self.text_response
        if response is None:
            raise AssertionError("FakeLLM.chat_text called but no text_response was scripted")
        return response

    def is_available(self) -> bool:
        return not self.down


def make_pdf(*page_texts: str) -> bytes:
    """A small text-based PDF with one page per string."""
    doc = pymupdf.open()
    for text in page_texts:
        page = doc.new_page()
        y = 72
        for line in text.splitlines():
            page.insert_text((72, y), line, fontsize=11)
            y += 16
    data = doc.tobytes()
    doc.close()
    return data


INVOICE_TEXT = """COMMERCIAL INVOICE
Invoice No: INV-1024
Invoice Date: 10 November 2026
Due Date: 25 December 2026
Exporter: Meridian Engineering Works Pvt Ltd
Buyer: Harbor & Pine Trading Co
Buyer Country: USA
Description: Hydraulic pump housings, 10 pallets
Currency: USD
Total Amount: USD 10,000.00
"""

GOOD_EXTRACTION = {
    "document_type": "COMMERCIAL_INVOICE",
    "invoice_number": "INV-1024",
    "exporter_name": "Meridian Engineering Works Pvt Ltd",
    "buyer_name": "Harbor & Pine Trading Co",
    "buyer_country": "USA",
    "currency": "USD",
    "invoice_amount": "10000.00",
    "invoice_date": "2026-11-10",
    "due_date": "2026-12-25",
    "confidence": {"invoice_number": 0.98, "invoice_amount": 0.95},
}


def rewrite_draft(prefix: str = "", *, numbered: bool = False):
    """A well-behaved 'model': rewords the DRAFT it is given without changing a single figure or reference."""
    import re

    def respond(system: str, user: str) -> str:
        match = re.search(r"DRAFT(?: ANSWER)?:\n(.*?)\n\nRewrite", user, re.DOTALL)
        assert match, "no draft found in the prompt"
        draft = match.group(1)
        if numbered:
            draft = "\n".join(f"{i}. {part.strip()}" for i, part in enumerate(re.split(r"(?<=[.;])\s+", draft), 1) if part.strip())
        return prefix + draft

    return respond
