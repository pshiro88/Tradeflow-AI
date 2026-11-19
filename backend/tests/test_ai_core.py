"""Unit tests for the AI building blocks: Ollama client, PDF validation, extraction validation + grounding."""

import json
from datetime import date
from decimal import Decimal

import httpx
import pymupdf
import pytest

from app.core.errors import AIResponseError, AIUnavailableError, BusinessValidationError, PayloadTooLargeError
from app.services.document_extraction import (
    ExtractedFields,
    assess_quality,
    extract_fields,
    output_schema,
    parse_llm_output,
)
from app.services.ollama_service import OllamaService
from app.services.pdf_service import validate_and_extract
from tests.fakes import GOOD_EXTRACTION, INVOICE_TEXT, FakeLLM, make_pdf

# ======================================================================== Ollama client


def ollama(handler) -> OllamaService:
    return OllamaService("http://ollama.test", "qwen2.5:3b", 5, transport=httpx.MockTransport(handler))


def reply(content: str, status: int = 200):
    return lambda request: httpx.Response(status, json={"message": {"role": "assistant", "content": content}})


def test_chat_json_sends_schema_and_deterministic_options():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": '{"a": 1}'}})

    schema = {"type": "object", "properties": {"a": {"type": "number"}}}
    assert ollama(handler).chat_json("sys", "usr", schema) == {"a": 1}
    body = seen["body"]
    assert seen["url"] == "http://ollama.test/api/chat"
    assert body["model"] == "qwen2.5:3b" and body["stream"] is False and body["format"] == schema
    assert body["options"]["temperature"] == 0
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


def test_chat_text_returns_stripped_content_without_a_format():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": "  hello  "}})

    assert ollama(handler).chat_text("s", "u") == "hello"
    assert "format" not in seen["body"]


@pytest.mark.parametrize("content", ["not json at all", "[1, 2, 3]", '"just a string"'])
def test_invalid_or_wrong_shaped_json_is_an_ai_response_error(content):
    with pytest.raises(AIResponseError):
        ollama(reply(content)).chat_json("s", "u", {})


def test_empty_text_answer_is_an_ai_response_error():
    with pytest.raises(AIResponseError):
        ollama(reply("   ")).chat_text("s", "u")


def test_unexpected_response_shape_is_an_ai_response_error():
    with pytest.raises(AIResponseError):
        ollama(lambda r: httpx.Response(200, json={"oops": True})).chat_text("s", "u")


def test_missing_model_gives_a_helpful_message():
    with pytest.raises(AIUnavailableError, match="ollama pull qwen2.5:3b"):
        ollama(lambda r: httpx.Response(404, json={"error": "model not found"})).chat_text("s", "u")


def test_server_error_is_unavailable():
    with pytest.raises(AIUnavailableError, match="HTTP 500"):
        ollama(lambda r: httpx.Response(500)).chat_text("s", "u")


def test_connection_failure_is_unavailable():
    def refuse(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(AIUnavailableError, match="not reachable"):
        ollama(refuse).chat_text("s", "u")


def test_timeout_is_unavailable_with_a_clear_message():
    def slow(request):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(AIUnavailableError, match="too long"):
        ollama(slow).chat_text("s", "u")


def test_is_available_checks_the_installed_models():
    tags = lambda names: (lambda r: httpx.Response(200, json={"models": [{"name": n} for n in names]}))  # noqa: E731
    assert ollama(tags(["qwen2.5:3b", "gemma2:2b"])).is_available() is True
    assert ollama(tags(["gemma2:2b"])).is_available() is False
    assert ollama(lambda r: httpx.Response(500)).is_available() is False

    def refuse(request):
        raise httpx.ConnectError("refused")

    assert ollama(refuse).is_available() is False


# ======================================================================== PDF validation

LIMITS = {"max_bytes": 1024 * 1024, "max_pages": 5}


def test_valid_pdf_returns_text_and_page_count():
    result = validate_and_extract(make_pdf(INVOICE_TEXT), **LIMITS)
    assert result.page_count == 1
    assert "INV-1024" in result.text and "10,000.00" in result.text


def test_multi_page_text_is_joined():
    result = validate_and_extract(make_pdf("First page content here.", "Second page content here."), **LIMITS)
    assert result.page_count == 2 and "First page" in result.text and "Second page" in result.text


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "empty"),
        (b"hello, I am a text file pretending to be a pdf", "not a PDF"),
        (b"%PDF-1.7\nthis is garbage after a valid looking header", "corrupted"),
        (b"\x89PNG\r\n\x1a\n" + b"0" * 100, "not a PDF"),
    ],
)
def test_invalid_files_are_rejected(content, message):
    with pytest.raises(BusinessValidationError, match=message):
        validate_and_extract(content, **LIMITS)


def test_oversized_file_is_rejected_before_parsing():
    with pytest.raises(PayloadTooLargeError):
        validate_and_extract(make_pdf(INVOICE_TEXT), max_bytes=100, max_pages=5)


def test_too_many_pages_are_rejected():
    with pytest.raises(BusinessValidationError, match="limit is 5"):
        validate_and_extract(make_pdf(*["Page of text content for the test."] * 6), **LIMITS)


def test_pdf_without_a_text_layer_is_rejected_with_an_ocr_hint():
    doc = pymupdf.open()
    doc.new_page()  # blank page: what a scan with no OCR looks like to a text extractor
    blank = doc.tobytes()
    with pytest.raises(BusinessValidationError, match="Scanned or image-only"):
        validate_and_extract(blank, **LIMITS)


def test_password_protected_pdf_is_rejected():
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Secret invoice text goes here for the test")
    locked = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    with pytest.raises(BusinessValidationError, match="Password-protected"):
        validate_and_extract(locked, **LIMITS)


# ======================================================================== extraction: validation


def test_good_output_is_parsed_into_typed_fields():
    fields, issues, confidence = parse_llm_output(GOOD_EXTRACTION)
    assert issues == []
    assert fields.invoice_number == "INV-1024" and fields.currency == "USD"
    assert fields.invoice_amount == Decimal("10000.00") and isinstance(fields.invoice_amount, Decimal)
    assert fields.invoice_date == date(2026, 11, 10) and fields.due_date == date(2026, 12, 25)
    assert fields.document_type.value == "COMMERCIAL_INVOICE"
    assert confidence == {"invoice_number": 0.98, "invoice_amount": 0.95}


@pytest.mark.parametrize("null_like", [None, "", "  ", "null", "N/A", "unknown", "None", "not available"])
def test_null_like_values_stay_null_and_are_not_flagged(null_like):
    raw = {name: null_like for name in ("invoice_number", "exporter_name", "buyer_name", "currency", "invoice_amount", "invoice_date")}
    fields, issues, _ = parse_llm_output(raw)
    assert fields == ExtractedFields() and issues == []


def test_missing_keys_are_simply_null():
    fields, issues, _ = parse_llm_output({})
    assert fields == ExtractedFields() and issues == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10000", "10000.00"), ("10000.00", "10000.00"), ("10,000.50", "10000.50"), ("USD 10,000.00", "10000.00"),
        ("$1,234.5", "1234.50"), (10000, "10000.00"), (10000.0, "10000.00"), (1234.56, "1234.56"), ("10000,50", "10000.50"),
    ],
)
def test_amount_formats_are_parsed_exactly(raw, expected):
    fields, issues, _ = parse_llm_output({"invoice_amount": raw})
    assert issues == [] and fields.invoice_amount == Decimal(expected)


@pytest.mark.parametrize("raw", ["abc", "-500", "0", "10.123", "1e999999", "ten thousand", "99999999999999999999", "1,2,3x", "10 000 USD extra", "1.2.3", "5 apples"])
def test_invalid_amounts_become_null_with_an_issue(raw):
    fields, issues, _ = parse_llm_output({"invoice_amount": raw})
    assert fields.invoice_amount is None
    assert [i.field for i in issues] == ["invoice_amount"]


@pytest.mark.parametrize("raw", ["10/11/2026", "10 November 2026", "2026-13-01", "2026-02-30", "yesterday", "2026/11/10"])
def test_non_iso_or_impossible_dates_are_rejected_not_guessed(raw):
    """'10/11/2026' is ambiguous (10 Nov or 11 Oct), so it is refused rather than interpreted."""
    fields, issues, _ = parse_llm_output({"invoice_date": raw, "due_date": raw})
    assert fields.invoice_date is None and fields.due_date is None
    assert {i.field for i in issues} == {"invoice_date", "due_date"}


@pytest.mark.parametrize("raw", ["US", "dollar", "USDX", "12$", "U SD"])
def test_invalid_currency_codes_are_rejected(raw):
    fields, issues, _ = parse_llm_output({"currency": raw})
    assert fields.currency is None and [i.field for i in issues] == ["currency"]


def test_currency_is_uppercased():
    assert parse_llm_output({"currency": " eur "})[0].currency == "EUR"


@pytest.mark.parametrize("raw", ["commercial invoice", "Commercial-Invoice", "COMMERCIAL_INVOICE", "remittance advice"])
def test_document_type_is_normalised(raw):
    assert parse_llm_output({"document_type": raw})[0].document_type is not None


def test_unknown_document_type_is_rejected():
    fields, issues, _ = parse_llm_output({"document_type": "love letter"})
    assert fields.document_type is None and issues[0].field == "document_type"


def test_overlong_strings_are_rejected():
    fields, issues, _ = parse_llm_output({"invoice_number": "X" * 65, "buyer_name": "B" * 256})
    assert fields.invoice_number is None and fields.buyer_name is None
    assert {i.field for i in issues} == {"invoice_number", "buyer_name"}


def test_whitespace_is_collapsed_and_unknown_keys_ignored():
    fields, _, _ = parse_llm_output({"buyer_name": "  Harbor   &\n Pine  ", "favourite_colour": "blue", "is_this_legit": True})
    assert fields.buyer_name == "Harbor & Pine" and not hasattr(fields, "favourite_colour")


def test_one_bad_field_does_not_discard_the_good_ones():
    fields, issues, _ = parse_llm_output({**GOOD_EXTRACTION, "invoice_amount": "lots", "due_date": "soon"})
    assert fields.invoice_number == "INV-1024" and fields.buyer_name == "Harbor & Pine Trading Co"
    assert fields.invoice_amount is None and fields.due_date is None
    assert {i.field for i in issues} == {"invoice_amount", "due_date"}


def test_confidence_accepts_fractions_and_percentages_and_ignores_nonsense():
    raw = {"invoice_number": 95, "currency": 1, "buyer_name": -2, "due_date": "high", "exporter_name": 150, "invoice_date": 0.5}
    _, _, confidence = parse_llm_output({"confidence": raw})
    assert confidence == {"invoice_number": 0.95, "currency": 1.0, "invoice_date": 0.5}  # out-of-range / non-numeric dropped


def test_malformed_confidence_container_is_ignored():
    assert parse_llm_output({"confidence": "very sure"})[2] == {}


# ======================================================================== extraction: grounding


def test_grounding_marks_values_present_in_the_text():
    fields, _, _ = parse_llm_output(GOOD_EXTRACTION)
    quality = assess_quality(fields, INVOICE_TEXT)
    assert quality["invoice_number"] == "FOUND_IN_TEXT"
    assert quality["exporter_name"] == "FOUND_IN_TEXT"
    assert quality["buyer_name"] == "FOUND_IN_TEXT"
    assert quality["invoice_amount"] == "FOUND_IN_TEXT"
    assert quality["currency"] == "FOUND_IN_TEXT"
    assert quality["invoice_date"] == "FOUND_IN_TEXT" and quality["due_date"] == "FOUND_IN_TEXT"
    assert quality["document_type"] == "INFERRED"


def test_grounding_flags_invented_values():
    invented = {**GOOD_EXTRACTION, "invoice_number": "INV-9999", "invoice_amount": "12345.67", "buyer_name": "Imaginary Corp", "invoice_date": "2025-01-01"}
    quality = assess_quality(parse_llm_output(invented)[0], INVOICE_TEXT)
    assert quality["invoice_number"] == "NOT_FOUND_IN_TEXT"
    assert quality["invoice_amount"] == "NOT_FOUND_IN_TEXT"
    assert quality["buyer_name"] == "NOT_FOUND_IN_TEXT"
    assert quality["invoice_date"] == "NOT_FOUND_IN_TEXT"
    assert quality["exporter_name"] == "FOUND_IN_TEXT"  # the honest fields stay green


def test_grounding_reports_missing_fields():
    quality = assess_quality(parse_llm_output({"invoice_number": "INV-1024"})[0], INVOICE_TEXT)
    assert quality["invoice_number"] == "FOUND_IN_TEXT" and quality["buyer_name"] == "MISSING"


@pytest.mark.parametrize(
    ("amount", "text", "expected"),
    [
        ("10000.00", "Total 10,000.00", "FOUND_IN_TEXT"),
        ("10000.00", "Total 10000.00", "FOUND_IN_TEXT"),
        ("10000.00", "Total 10,000", "FOUND_IN_TEXT"),
        ("100.00", "Total 1,100.00", "NOT_FOUND_IN_TEXT"),  # must not match inside a bigger number
        ("100.00", "Quantity 2100.00", "NOT_FOUND_IN_TEXT"),
        ("100.00", "Total 100.00 USD", "FOUND_IN_TEXT"),
    ],
)
def test_amount_grounding_respects_number_boundaries(amount, text, expected):
    fields = parse_llm_output({"invoice_amount": amount})[0]
    assert assess_quality(fields, text)["invoice_amount"] == expected


@pytest.mark.parametrize("text", ["Date: 2026-11-10", "10 November 2026", "10 Nov 2026", "November 10, 2026", "10/11/2026", "10-11-2026", "10.11.2026"])
def test_date_grounding_accepts_common_layouts(text):
    fields = parse_llm_output({"invoice_date": "2026-11-10"})[0]
    assert assess_quality(fields, text)["invoice_date"] == "FOUND_IN_TEXT"


def test_name_grounding_ignores_punctuation_case_and_accents():
    fields = parse_llm_output({"buyer_name": "Lumière Distribution SAS"})[0]
    assert assess_quality(fields, "BUYER: LUMIERE DISTRIBUTION S.A.S.")["buyer_name"] != "MISSING"
    fields = parse_llm_output({"exporter_name": "ABC Exports Pvt Ltd"})[0]
    assert assess_quality(fields, "abc exports pvt. ltd., Mumbai")["exporter_name"] == "FOUND_IN_TEXT"


# ======================================================================== extraction: orchestration


def test_extract_fields_runs_the_whole_pipeline():
    llm = FakeLLM(json_response=GOOD_EXTRACTION)
    outcome = extract_fields(llm, INVOICE_TEXT, max_chars=12000)
    assert outcome.fields.invoice_amount == Decimal("10000.00")
    assert outcome.quality["invoice_number"] == "FOUND_IN_TEXT"
    assert outcome.model == "fake-model" and outcome.truncated is False and outcome.issues == []
    call = llm.json_calls[0]
    assert INVOICE_TEXT in call["user"] and "null" in call["system"] and "NEVER guess" in call["system"]
    assert call["schema"] == output_schema()


def test_long_documents_are_truncated_and_flagged():
    llm = FakeLLM(json_response={})
    outcome = extract_fields(llm, "word " * 5000, max_chars=1000)
    assert outcome.truncated is True
    assert len(llm.json_calls[0]["user"]) < 1200


def test_an_ai_hallucination_is_caught_end_to_end():
    llm = FakeLLM(json_response={**GOOD_EXTRACTION, "invoice_amount": "99999.00"})
    outcome = extract_fields(llm, INVOICE_TEXT, max_chars=12000)
    assert outcome.quality["invoice_amount"] == "NOT_FOUND_IN_TEXT"


def test_llm_failures_propagate_for_the_caller_to_handle():
    with pytest.raises(AIUnavailableError):
        extract_fields(FakeLLM(down=True), INVOICE_TEXT, max_chars=12000)


def test_output_schema_requires_every_field_but_allows_null():
    schema = output_schema()
    assert set(schema["required"]) >= {"invoice_number", "invoice_amount", "due_date"}
    # numeric on purpose: a string-typed amount made the real model return null every time (see output_schema)
    assert schema["properties"]["invoice_amount"]["type"] == ["number", "null"]
    assert schema["properties"]["invoice_number"]["type"] == ["string", "null"]
    assert all("description" in schema["properties"][name] for name in schema["required"])
