"""Workflow state entity."""

from dataclasses import dataclass, field
from typing import Any

from autopilot.domain.value_objects.error_record import ErrorRecord
from autopilot.domain.value_objects.evidence import EvidenceItem
from autopilot.domain.value_objects.log_entry import LogEntry


@dataclass
class WorkflowState:
    """Shared state object that flows through the orchestration graph."""

    ticket: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    modified_files: list[str] = field(default_factory=list)
    plan: dict[str, Any] = field(default_factory=dict)
    logs: list[LogEntry] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    errors: list[ErrorRecord] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
