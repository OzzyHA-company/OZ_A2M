"""Custom exceptions for OZ_A2M."""


class OZA2MError(Exception):
    """Base exception for OZ_A2M."""

    def __init__(self, message: str, code: str = "INTERNAL_ERROR", details: dict = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class ValidationError(OZA2MError):
    """Validation error."""

    def __init__(self, message: str = "Validation failed", details: dict = None):
        super().__init__(message, "VALIDATION_ERROR", details)


class AuthenticationError(OZA2MError):
    """Authentication error."""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, "AUTHENTICATION_ERROR")


class AuthorizationError(OZA2MError):
    """Authorization error."""

    def __init__(self, message: str = "Access denied"):
        super().__init__(message, "AUTHORIZATION_ERROR")


class NotFoundError(OZA2MError):
    """Resource not found error."""

    def __init__(self, message: str = "Resource not found"):
        super().__init__(message, "NOT_FOUND")


class ConflictError(OZA2MError):
    """Conflict error."""

    def __init__(self, message: str = "Conflict detected"):
        super().__init__(message, "CONFLICT")


class RateLimitError(OZA2MError):
    """Rate limit exceeded error."""

    def __init__(self, message: str = "Rate limit exceeded", retry_after: int = 60):
        super().__init__(message, "RATE_LIMIT")
        self.retry_after = retry_after


class ServiceUnavailableError(OZA2MError):
    """Service unavailable error."""

    def __init__(self, message: str = "Service temporarily unavailable"):
        super().__init__(message, "SERVICE_UNAVAILABLE")


class TradingError(OZA2MError):
    """Trading error."""

    def __init__(self, message: str = "Trading operation failed", details: dict = None):
        super().__init__(message, "TRADING_ERROR", details)
