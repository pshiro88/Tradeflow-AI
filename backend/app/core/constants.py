"""Business constants shared across modules."""

# ISO 4217 codes the MVP supports (BRD FR-006 / FR-011).
SUPPORTED_CURRENCIES: tuple[str, ...] = ("USD", "EUR", "GBP", "AED", "INR")

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
