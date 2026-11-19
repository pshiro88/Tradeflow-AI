import enum


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    FINANCE = "FINANCE"
    OPERATIONS = "OPERATIONS"


class InvoiceStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"


class ReconciliationStatus(str, enum.Enum):
    """Reconciliation outcome. PENDING means the payment has not been processed yet."""

    PENDING = "PENDING"
    MATCHED = "MATCHED"
    PARTIAL = "PARTIAL"
    UNMATCHED = "UNMATCHED"
    MISMATCH = "MISMATCH"
    DUPLICATE = "DUPLICATE"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class AllocationType(str, enum.Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


class ReviewDecision(str, enum.Enum):
    NONE = "NONE"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DocumentType(str, enum.Enum):
    COMMERCIAL_INVOICE = "COMMERCIAL_INVOICE"
    PACKING_LIST = "PACKING_LIST"
    SHIPPING_BILL = "SHIPPING_BILL"
    BILL_OF_LADING = "BILL_OF_LADING"
    REMITTANCE_ADVICE = "REMITTANCE_ADVICE"
    OTHER = "OTHER"


class ExtractionStatus(str, enum.Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DocumentStatus(str, enum.Enum):
    """Checklist / verification status of a trade document."""

    NOT_UPLOADED = "NOT_UPLOADED"
    UPLOADED = "UPLOADED"
    UNDER_REVIEW = "UNDER_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
