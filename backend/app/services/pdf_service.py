"""PDF validation and text extraction with PyMuPDF (BRD FR-020 / FR-021).

MVP scope: text-based PDFs only. A scanned PDF has no text layer, so it is rejected with a clear message
(OCR is a documented future enhancement). Document content is never logged.
"""

from dataclasses import dataclass

import pymupdf

from app.core.errors import BusinessValidationError, PayloadTooLargeError

MIN_TEXT_CHARS = 20  # fewer characters than this means "no text layer"


@dataclass(frozen=True)
class PdfText:
    text: str
    page_count: int


def validate_and_extract(content: bytes, *, max_bytes: int, max_pages: int) -> PdfText:
    """Validate an uploaded PDF and return its text. Raises BusinessValidationError / PayloadTooLargeError."""
    if not content:
        raise BusinessValidationError("The file is empty")
    if len(content) > max_bytes:
        raise PayloadTooLargeError(f"The file is larger than the {max_bytes // (1024 * 1024)} MB limit")
    # Check the magic bytes rather than trusting the extension or the client's content type.
    if not content[:1024].lstrip().startswith(b"%PDF-"):
        raise BusinessValidationError("The file is not a PDF")

    try:
        doc = pymupdf.open(stream=content, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises several error types for corrupt input
        raise BusinessValidationError("The PDF is corrupted or cannot be read") from exc

    try:
        if doc.needs_pass or doc.is_encrypted:
            raise BusinessValidationError("Password-protected PDFs are not supported")
        if doc.page_count == 0:
            raise BusinessValidationError("The PDF has no pages")
        if doc.page_count > max_pages:
            raise BusinessValidationError(f"The PDF has {doc.page_count} pages; the limit is {max_pages}")
        try:
            pages = [page.get_text("text") for page in doc]
        except Exception as exc:
            raise BusinessValidationError("The PDF is corrupted or cannot be read") from exc
        page_count = doc.page_count
    finally:
        doc.close()

    text = "\n".join(pages).strip()
    if len(text) < MIN_TEXT_CHARS:
        raise BusinessValidationError(
            "No readable text found. Scanned or image-only PDFs are not supported yet; upload a text-based PDF."
        )
    return PdfText(text=text, page_count=page_count)
