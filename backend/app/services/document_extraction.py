"""Structured extraction of invoice fields from document text (BRD FR-022 / FR-024).

Pipeline:  document text -> LLM (JSON schema constrained) -> per-field validation (Pydantic) -> grounding check.

Principles:
  * The model must return null for anything it cannot find. We never fill gaps.
  * Every value is validated; an invalid value becomes null and is reported as an issue, never "fixed".
  * LLM self-reported confidence is an ESTIMATE, not a probability. The reliable quality signal is the
    deterministic grounding check: does the extracted value literally appear in the source text?
  * Nothing here writes financial records. A person confirms the result first.
"""

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import DocumentType
from app.services.ollama_service import LLMClient

FIELD_NAMES = (
    "document_type",
    "invoice_number",
    "exporter_name",
    "buyer_name",
    "buyer_country",
    "currency",
    "invoice_amount",
    "invoice_date",
    "due_date",
)
STRING_FIELDS = ("invoice_number", "exporter_name", "buyer_name", "buyer_country")
MAX_LENGTH = {"invoice_number": 64, "exporter_name": 255, "buyer_name": 255, "buyer_country": 100}
DATE_FIELDS = ("invoice_date", "due_date")

Quality = Literal["FOUND_IN_TEXT", "NOT_FOUND_IN_TEXT", "INFERRED", "MISSING"]

_NULL_WORDS = {"", "null", "none", "n/a", "na", "unknown", "not available", "not provided", "-", "—"}
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_AMOUNT = Decimal("9999999999999999.99")


class ExtractedFields(BaseModel):
    """Validated extraction result. Every field is optional: unknown stays None."""

    document_type: DocumentType | None = None
    invoice_number: str | None = Field(default=None, max_length=MAX_LENGTH["invoice_number"])
    exporter_name: str | None = Field(default=None, max_length=MAX_LENGTH["exporter_name"])
    buyer_name: str | None = Field(default=None, max_length=MAX_LENGTH["buyer_name"])
    buyer_country: str | None = Field(default=None, max_length=MAX_LENGTH["buyer_country"])
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    invoice_amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    invoice_date: date | None = None
    due_date: date | None = None


class FieldIssue(BaseModel):
    field: str
    message: str


class ExtractionOutcome(BaseModel):
    fields: ExtractedFields
    quality: dict[str, Quality]
    llm_confidence: dict[str, float]  # an estimate reported by the model; never proof of correctness
    issues: list[FieldIssue]
    model: str
    truncated: bool


# ======================================================================== prompt and schema


# Per-field guidance placed in the JSON schema itself, which small models follow more reliably than prose.
FIELD_HINTS = {
    "document_type": "Kind of document, e.g. COMMERCIAL_INVOICE.",
    "invoice_number": "The invoice number exactly as written, e.g. INV-1024.",
    "exporter_name": "Company that issued the invoice and sells the goods.",
    "buyer_name": "Company that buys the goods.",
    "buyer_country": "Country of the buyer.",
    "currency": "3-letter ISO currency code of the total, e.g. USD.",
    "invoice_amount": (
        "The grand total as a number, from the line labelled Total, Total Amount or Amount Due "
        "(not a unit price). Example: 'Total Amount: USD 10,000.00' gives 10000.00. null if there is no total."
    ),
    "invoice_date": "Invoice issue date as YYYY-MM-DD.",
    "due_date": "Payment due date as YYYY-MM-DD.",
}


def output_schema() -> dict[str, Any]:
    """JSON schema that constrains the model's output.

    invoice_amount is typed `number|null`, not string: measured against qwen2.5:3b on the sample invoices,
    a string-typed amount came back null every time (0/4) while a numeric one was found every time (4/4).
    null stays allowed so the model can still say "no total in this document".
    """
    properties: dict[str, Any] = {
        name: {"type": ["number", "null"] if name == "invoice_amount" else ["string", "null"], "description": hint}
        for name, hint in FIELD_HINTS.items()
    }
    properties["confidence"] = {
        "type": "object",
        "properties": {name: {"type": "number"} for name in FIELD_NAMES},
    }
    return {"type": "object", "properties": properties, "required": list(FIELD_NAMES)}


SYSTEM_PROMPT = (
    "You extract structured data from a trade document's text. "
    "Return ONLY a JSON object. "
    "Use null for any field that is not explicitly present in the text. NEVER guess, infer or invent a value. "
    "Copy names, numbers and references exactly as written. "
    "Dates must be formatted YYYY-MM-DD. "
    "invoice_amount is the grand TOTAL (the line labelled Total, Total Amount or Amount Due, not a unit price) "
    "as a plain number without currency symbols or thousands separators, e.g. 10000.00. "
    "currency is the 3-letter ISO code. "
    "document_type is one of: COMMERCIAL_INVOICE, PACKING_LIST, SHIPPING_BILL, BILL_OF_LADING, "
    "REMITTANCE_ADVICE, OTHER. "
    "In 'confidence' give each field a number from 0 to 1 for how sure you are."
)


def build_user_prompt(text: str) -> str:
    return f"Document text:\n\n{text}\n\nExtract the fields."


# ======================================================================== validation


def _clean_string(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return None if text.lower() in _NULL_WORDS else text


_CURRENCY_AFFIX = re.compile(r"^[A-Za-z]{3}\s*|\s*[A-Za-z]{3}$")
_AMOUNT_BODY = re.compile(r"^\d[\d,]*(\.\d+)?$|^\d+,\d{1,2}$")


def _clean_amount(value: Any) -> Decimal | None:
    """Parse money strictly. Only a leading/trailing currency code or symbol may be stripped; any other
    stray character means the text is not a plain amount and is rejected (never silently 'repaired')."""
    if value is None or isinstance(value, bool):
        return None
    raw = str(value).strip()
    if raw.lower() in _NULL_WORDS:
        return None
    body = _CURRENCY_AFFIX.sub("", raw.translate({ord(c): None for c in "$€£₹"})).strip().replace(" ", "")
    if not _AMOUNT_BODY.match(body):
        raise ValueError(f"'{raw}' is not a valid amount")
    if "," in body and "." in body:
        body = body.replace(",", "")  # 10,000.50
    elif body.count(",") == 1 and re.search(r",\d{1,2}$", body):
        body = body.replace(",", ".")  # 10000,50 (decimal comma)
    else:
        body = body.replace(",", "")
    try:
        amount = Decimal(body)
    except InvalidOperation:
        raise ValueError(f"'{raw}' is not a valid amount") from None
    if amount <= 0:
        raise ValueError("amount must be greater than zero")
    if amount > _MAX_AMOUNT:
        raise ValueError("amount is too large")
    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("amount has more than 2 decimal places")
    return amount.quantize(Decimal("0.01"))


def _clean_date(value: Any) -> date | None:
    text = _clean_string(value)
    if text is None:
        return None
    if not _ISO_DATE.match(text):
        raise ValueError(f"'{text}' is not in YYYY-MM-DD format")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"'{text}' is not a real calendar date") from None


def parse_llm_output(raw: dict[str, Any]) -> tuple[ExtractedFields, list[FieldIssue], dict[str, float]]:
    """Validate the model's JSON field by field. Bad values become None plus an issue; nothing is repaired."""
    cleaned: dict[str, Any] = {}
    issues: list[FieldIssue] = []

    for name in FIELD_NAMES:
        value = raw.get(name)
        try:
            if name == "document_type":
                text = _clean_string(value)
                if text is not None:
                    code = re.sub(r"[\s\-]+", "_", text).upper()
                    if code not in {t.value for t in DocumentType}:
                        raise ValueError(f"'{text}' is not a known document type")
                    cleaned[name] = code
            elif name == "currency":
                text = _clean_string(value)
                if text is not None:
                    code = text.upper()
                    if not re.fullmatch(r"[A-Z]{3}", code):
                        raise ValueError(f"'{text}' is not a 3-letter currency code")
                    cleaned[name] = code
            elif name == "invoice_amount":
                amount = _clean_amount(value)
                if amount is not None:
                    cleaned[name] = amount
            elif name in DATE_FIELDS:
                parsed = _clean_date(value)
                if parsed is not None:
                    cleaned[name] = parsed
            else:
                text = _clean_string(value)
                if text is not None:
                    limit = MAX_LENGTH[name]
                    if len(text) > limit:
                        raise ValueError(f"longer than {limit} characters")
                    cleaned[name] = text
        except ValueError as exc:
            issues.append(FieldIssue(field=name, message=str(exc)))

    # Final gate: the Pydantic model is the contract for everything we keep.
    fields = ExtractedFields.model_validate(cleaned)

    confidence: dict[str, float] = {}
    reported = raw.get("confidence")
    if isinstance(reported, dict):
        for name in FIELD_NAMES:
            value = reported.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 100:
                # 0-1 is a fraction; above 1 up to 100 is read as a percentage. Anything else is untrustworthy.
                confidence[name] = round(float(value) / 100 if value > 1 else float(value), 2)
    return fields, issues, confidence


# ======================================================================== grounding


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _amount_in_text(amount: Decimal, text: str) -> bool:
    candidates = {f"{amount:,.2f}", f"{amount:.2f}"}
    if amount == amount.to_integral_value():
        candidates |= {f"{int(amount):,}", str(int(amount))}
    return any(re.search(rf"(?<![\d.,]){re.escape(c)}(?![\d])", text) for c in candidates)


def _date_in_text(d: date, text: str) -> bool:
    lowered = text.lower()
    forms = {
        d.isoformat(),
        f"{d.day} {d.strftime('%B %Y')}",
        f"{d.day} {d.strftime('%b %Y')}",
        f"{d.day:02d} {d.strftime('%B %Y')}",
        f"{d.day:02d} {d.strftime('%b %Y')}",
        f"{d.day} {d.strftime('%B')}, {d.year}",
        f"{d.strftime('%B')} {d.day}, {d.year}",
        f"{d.strftime('%b')} {d.day}, {d.year}",
        f"{d.day:02d}/{d.month:02d}/{d.year}",
        f"{d.day:02d}-{d.month:02d}-{d.year}",
        f"{d.day:02d}.{d.month:02d}.{d.year}",
        f"{d.month:02d}/{d.day:02d}/{d.year}",
    }
    return any(form.lower() in lowered for form in forms)


def assess_quality(fields: ExtractedFields, text: str) -> dict[str, Quality]:
    """Deterministic per-field check: does the value literally appear in the document text?

    FOUND_IN_TEXT      the value is present in the source (still worth a glance, but not invented)
    NOT_FOUND_IN_TEXT  the model returned it but it is not in the text: likely a hallucination, verify it
    INFERRED           document_type is a judgement, not text to find
    MISSING            nothing extracted
    """
    normalised_text = _normalise(text)
    result: dict[str, Quality] = {}
    for name in FIELD_NAMES:
        value = getattr(fields, name)
        if value is None:
            result[name] = "MISSING"
        elif name == "document_type":
            result[name] = "INFERRED"
        elif name == "invoice_amount":
            result[name] = "FOUND_IN_TEXT" if _amount_in_text(value, text) else "NOT_FOUND_IN_TEXT"
        elif name in DATE_FIELDS:
            result[name] = "FOUND_IN_TEXT" if _date_in_text(value, text) else "NOT_FOUND_IN_TEXT"
        elif name == "currency":
            result[name] = "FOUND_IN_TEXT" if re.search(rf"\b{value}\b", text, re.IGNORECASE) else "NOT_FOUND_IN_TEXT"
        else:
            needle = _normalise(str(value))
            result[name] = "FOUND_IN_TEXT" if needle and needle in normalised_text else "NOT_FOUND_IN_TEXT"
    return result


# ======================================================================== orchestration


def extract_fields(llm: LLMClient, text: str, *, max_chars: int) -> ExtractionOutcome:
    """Run the full pipeline. Raises AIUnavailableError / AIResponseError from the LLM client."""
    truncated = len(text) > max_chars
    prompt_text = text[:max_chars]
    raw = llm.chat_json(SYSTEM_PROMPT, build_user_prompt(prompt_text), output_schema())
    fields, issues, confidence = parse_llm_output(raw)
    return ExtractionOutcome(
        fields=fields,
        quality=assess_quality(fields, prompt_text),
        llm_confidence=confidence,
        issues=issues,
        model=llm.model,
        truncated=truncated,
    )
