"""Error record value object."""

from dataclasses import dataclass
from enum import Enum


class ErrorType(Enum):
    """Classification of error types for retry decisions."""

    RETRYABLE = "retryable"
    NON_RETRYABLE = "non_retryable"


@dataclass
class ErrorRecord:
    """Record of an error during workflow execution."""

    error_type: ErrorType
    description: str
    agent_name: str
    attempt_count: int = 0
    exception_class: str = ""
