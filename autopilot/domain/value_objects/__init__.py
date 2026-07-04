"""Domain value objects."""

from autopilot.domain.value_objects.error_record import ErrorRecord, ErrorType
from autopilot.domain.value_objects.evidence import EvidenceItem
from autopilot.domain.value_objects.exceptions import (
    AuthenticationError,
    ConfigurationError,
    SchemaViolationError,
    TestFailureError,
    ToolTimeoutError,
)
from autopilot.domain.value_objects.log_entry import LogEntry, StepStatus
from autopilot.domain.value_objects.metrics import Metrics
from autopilot.domain.value_objects.search_criteria import SearchCriteria

__all__ = [
    "AuthenticationError",
    "ConfigurationError",
    "ErrorRecord",
    "ErrorType",
    "EvidenceItem",
    "LogEntry",
    "Metrics",
    "SchemaViolationError",
    "SearchCriteria",
    "StepStatus",
    "TestFailureError",
    "ToolTimeoutError",
]
