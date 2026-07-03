"""Custom domain exceptions for error classification."""


class TestFailureError(Exception):
    """Raised when a test suite execution fails."""

    pass


class ToolTimeoutError(Exception):
    """Raised when a tool execution exceeds its timeout."""

    pass


class AuthenticationError(Exception):
    """Raised when authentication with an external service fails."""

    pass


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""

    pass


class SchemaViolationError(Exception):
    """Raised when data does not conform to its expected schema."""

    pass
