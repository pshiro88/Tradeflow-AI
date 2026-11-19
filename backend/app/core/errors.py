class DomainError(Exception):
    """A business-rule failure that maps to an HTTP status. The message is safe to show to clients."""

    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(DomainError):
    status_code = 404


class ConflictError(DomainError):
    """The request is valid but conflicts with current state (duplicate, locked record, ...)."""

    status_code = 409


class BusinessValidationError(DomainError):
    """Well-formed input that violates a business rule."""

    status_code = 422


class PayloadTooLargeError(DomainError):
    status_code = 413


class AIUnavailableError(DomainError):
    """The local LLM (Ollama) is not reachable, timed out, or is missing the model."""

    status_code = 503


class AIResponseError(DomainError):
    """The LLM answered, but not with something usable (invalid JSON, wrong shape)."""

    status_code = 502
