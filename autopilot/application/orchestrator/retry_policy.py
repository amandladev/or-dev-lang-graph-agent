"""Error classification and retry logic for the orchestration engine."""

from autopilot.domain.value_objects.error_record import ErrorType
from autopilot.domain.value_objects.exceptions import (
    AuthenticationError,
    ConfigurationError,
    SchemaViolationError,
    TestFailureError,
    ToolTimeoutError,
)


class RetryPolicy:
    """Classifies errors and determines retry behavior with exponential backoff."""

    RETRYABLE_EXCEPTIONS: set[type] = {
        TimeoutError,
        ConnectionError,
        TestFailureError,
        ToolTimeoutError,
    }

    NON_RETRYABLE_EXCEPTIONS: set[type] = {
        AuthenticationError,
        ConfigurationError,
        SchemaViolationError,
    }

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 2.0,
        backoff_multiplier: float = 2.0,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.backoff_multiplier = backoff_multiplier

    def classify(self, exception: Exception) -> ErrorType:
        """Classify an exception as retryable or non-retryable.

        Checks the exception type against the RETRYABLE_EXCEPTIONS set.
        If it matches any retryable type (including subclasses), returns RETRYABLE.
        Otherwise returns NON_RETRYABLE.

        Args:
            exception: The exception instance to classify.

        Returns:
            ErrorType.RETRYABLE if the exception is transient and recoverable,
            ErrorType.NON_RETRYABLE otherwise.
        """
        for exc_type in self.RETRYABLE_EXCEPTIONS:
            if isinstance(exception, exc_type):
                return ErrorType.RETRYABLE
        return ErrorType.NON_RETRYABLE

    def get_delay(self, attempt: int) -> float:
        """Calculate the delay before the next retry attempt using exponential backoff.

        Formula: base_delay * backoff_multiplier^attempt

        Args:
            attempt: The zero-indexed attempt number (0 for first retry, 1 for second, etc.)

        Returns:
            The delay in seconds before the next retry.
        """
        return self.base_delay * (self.backoff_multiplier ** attempt)
