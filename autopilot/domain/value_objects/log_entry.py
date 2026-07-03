"""Log entry value object."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class StepStatus(Enum):
    """Status of an agent execution step."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class LogEntry:
    """Structured log entry for a single agent execution step."""

    agent_name: str
    start_time: datetime
    end_time: datetime
    elapsed_ms: int
    input_data: dict
    output_data: dict
    status: StepStatus
