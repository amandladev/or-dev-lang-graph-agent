"""Evidence item value object."""

from dataclasses import dataclass


@dataclass
class EvidenceItem:
    """Evidence produced during workflow execution."""

    type: str  # "test_result", "screenshot", "log_file"
    description: str
    path: str | None = None
    data: dict | None = None
