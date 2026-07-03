"""Metrics value object."""

from dataclasses import dataclass


@dataclass
class Metrics:
    """Workflow execution metrics."""

    total_duration_ms: int = 0
    steps_executed: int = 0
    steps_failed: int = 0
    steps_skipped: int = 0
