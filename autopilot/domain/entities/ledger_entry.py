"""Ledger entry entity for audit trail.

The ledger is the single source of truth for tracking all workflow executions.
Each entry represents one complete run, stored in a central ledger.json file.
The ledger is committed to a dedicated git branch for version control.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class LedgerEntry:
    """A single entry in the audit ledger.

    Attributes:
        run_id: Unique identifier for the run.
        ticket_id: Jira ticket ID processed.
        ticket_title: Title of the Jira ticket.
        timestamp: ISO timestamp when the entry was created.
        status: Final status ("completed", "failed", "cancelled").
        verdict: Final verdict ("PASS", "PASS_WITH_OBS", "FAIL", "BLOCKED", None).
        modified_files: List of files modified during execution.
        duration_seconds: Total duration in seconds.
        summary: Short description of the result.
        tags: Tags for categorization.
        errors: Number of errors encountered.
        tests_executed: Number of tests executed.
        tests_passed: Number of tests that passed.
    """

    run_id: str = ""
    ticket_id: str = ""
    ticket_title: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    status: str = "completed"
    verdict: str | None = None
    modified_files: list[str] = field(default_factory=list)
    duration_seconds: int | None = None
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    errors: int = 0
    tests_executed: int = 0
    tests_passed: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation of the ledger entry.
        """
        return {
            "run_id": self.run_id,
            "ticket_id": self.ticket_id,
            "ticket_title": self.ticket_title,
            "timestamp": self.timestamp,
            "status": self.status,
            "verdict": self.verdict,
            "modified_files": self.modified_files,
            "duration_seconds": self.duration_seconds,
            "summary": self.summary,
            "tags": self.tags,
            "errors": self.errors,
            "tests_executed": self.tests_executed,
            "tests_passed": self.tests_passed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LedgerEntry":
        """Create a LedgerEntry from a dictionary.

        Args:
            data: Dictionary representation of a ledger entry.

        Returns:
            LedgerEntry instance.
        """
        return cls(
            run_id=data.get("run_id", ""),
            ticket_id=data.get("ticket_id", ""),
            ticket_title=data.get("ticket_title", ""),
            timestamp=data.get("timestamp", ""),
            status=data.get("status", "completed"),
            verdict=data.get("verdict"),
            modified_files=data.get("modified_files", []),
            duration_seconds=data.get("duration_seconds"),
            summary=data.get("summary", ""),
            tags=data.get("tags", []),
            errors=data.get("errors", 0),
            tests_executed=data.get("tests_executed", 0),
            tests_passed=data.get("tests_passed", 0),
        )

    @classmethod
    def from_run_record(cls, record: "RunRecord") -> "LedgerEntry":
        """Create a LedgerEntry from a RunRecord.

        Args:
            record: The RunRecord to convert.

        Returns:
            LedgerEntry instance.
        """
        # Generate a short summary based on verdict
        verdict = record.verdict or "UNKNOWN"
        summary = f"{verdict}: {record.tests_passed}/{record.tests_executed} tests passed"

        return cls(
            run_id=record.run_id,
            ticket_id=record.ticket_id,
            ticket_title=record.ticket_title,
            timestamp=record.finished_at or record.started_at,
            status=record.status,
            verdict=record.verdict,
            modified_files=record.modified_files,
            duration_seconds=record.duration_seconds,
            summary=summary,
            tags=[],
            errors=len(record.errors),
            tests_executed=record.tests_executed,
            tests_passed=record.tests_passed,
        )

    @classmethod
    def validate(cls, data: dict) -> list[str]:
        """Validate a ledger entry dictionary.

        Args:
            data: Dictionary to validate.

        Returns:
            List of warning messages (empty if valid).
        """
        warnings = []
        required_fields = ["run_id", "ticket_id", "timestamp", "status"]
        for field_name in required_fields:
            if field_name not in data:
                warnings.append(f"Missing required field: {field_name}")

        valid_statuses = ["completed", "failed", "cancelled"]
        if data.get("status") not in valid_statuses:
            warnings.append(f"Invalid status: {data.get('status')!r}")

        valid_verdicts = [None, "PASS", "PASS_WITH_OBS", "FAIL", "BLOCKED"]
        if data.get("verdict") not in valid_verdicts:
            warnings.append(f"Invalid verdict: {data.get('verdict')!r}")

        return warnings
