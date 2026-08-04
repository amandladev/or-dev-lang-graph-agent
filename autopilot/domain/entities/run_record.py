"""Run record entity for tracking execution results.

Every workflow execution produces a RunRecord that captures the complete
lifecycle of a run: from start to finish, including all intermediate state,
test results, errors, and metrics. This is the authoritative artifact for
auditing and replaying executions.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class RunRecord:
    """Complete record of a workflow execution.

    Attributes:
        run_id: Unique identifier for this run.
        ticket_id: Jira ticket ID being processed.
        ticket_title: Title of the Jira ticket.
        started_at: ISO timestamp when the run started.
        finished_at: ISO timestamp when the run finished (None if still running).
        duration_seconds: Total duration in seconds (None if still running).
        mode: Execution mode ("live", "dry-run", "resume").
        status: Current status ("running", "completed", "failed", "cancelled").
        verdict: Final verdict ("PASS", "PASS_WITH_OBS", "FAIL", "BLOCKED", None).
        plan: The plan that was executed (None if not yet planned).
        modified_files: List of files modified during execution.
        tests_executed: Number of tests executed.
        tests_passed: Number of tests that passed.
        tests_failed: Number of tests that failed.
        logs: List of log entries from execution.
        errors: List of errors encountered.
        evidence: List of evidence items collected.
        tokens_used: Token usage metrics (None if not tracked). NOTE: no
            current agent or tool reports this back to the engine, so this
            field is always None in practice — it exists for a future
            integration with a token-reporting OpenCode/LLM call.
        cost_usd: Cost in USD (None if not tracked). Same caveat as
            tokens_used: never populated by the current codebase.
        metadata: Additional metadata for extensibility.
    """

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ticket_id: str = ""
    ticket_title: str = ""
    started_at: str = field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    finished_at: str | None = None
    duration_seconds: int | None = None
    mode: str = "live"
    status: str = "running"
    verdict: str | None = None
    plan: dict | None = None
    modified_files: list[str] = field(default_factory=list)
    tests_executed: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    logs: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    tokens_used: dict | None = None
    cost_usd: float | None = None
    metadata: dict = field(default_factory=dict)

    def mark_completed(self, verdict: str) -> None:
        """Mark the run as completed with a verdict.

        Args:
            verdict: The final verdict ("PASS", "PASS_WITH_OBS", "FAIL", "BLOCKED").
        """
        self.status = "completed"
        self.verdict = verdict
        self.finished_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        if self.started_at:
            started = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
            finished = datetime.fromisoformat(self.finished_at.replace("Z", "+00:00"))
            self.duration_seconds = int((finished - started).total_seconds())

    def mark_failed(self, error: str) -> None:
        """Mark the run as failed.

        Args:
            error: Description of the failure.
        """
        self.status = "failed"
        self.finished_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.errors.append({
            "type": "run_failure",
            "description": error,
            "timestamp": self.finished_at,
        })
        if self.started_at:
            started = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
            finished = datetime.fromisoformat(self.finished_at.replace("Z", "+00:00"))
            self.duration_seconds = int((finished - started).total_seconds())

    def mark_cancelled(self) -> None:
        """Mark the run as cancelled."""
        self.status = "cancelled"
        self.finished_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        if self.started_at:
            started = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
            finished = datetime.fromisoformat(self.finished_at.replace("Z", "+00:00"))
            self.duration_seconds = int((finished - started).total_seconds())

    def add_log(self, log_entry: dict) -> None:
        """Add a log entry to the record.

        Args:
            log_entry: Log entry dict with agent_name, status, etc.
        """
        self.logs.append(log_entry)

    def add_error(self, error: dict) -> None:
        """Add an error to the record.

        Args:
            error: Error dict with type, description, etc.
        """
        self.errors.append(error)

    def add_evidence(self, evidence_item: dict) -> None:
        """Add an evidence item to the record.

        Args:
            evidence_item: Evidence dict with type, description, path, etc.
        """
        self.evidence.append(evidence_item)

    def update_test_counts(self, executed: int, passed: int, failed: int) -> None:
        """Update test execution counts.

        Args:
            executed: Total tests executed.
            passed: Tests that passed.
            failed: Tests that failed.
        """
        self.tests_executed = executed
        self.tests_passed = passed
        self.tests_failed = failed

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation of the run record.
        """
        return {
            "run_id": self.run_id,
            "ticket_id": self.ticket_id,
            "ticket_title": self.ticket_title,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "mode": self.mode,
            "status": self.status,
            "verdict": self.verdict,
            "plan": self.plan,
            "modified_files": self.modified_files,
            "tests_executed": self.tests_executed,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "logs": self.logs,
            "errors": self.errors,
            "evidence": self.evidence,
            "tokens_used": self.tokens_used,
            "cost_usd": self.cost_usd,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RunRecord":
        """Create a RunRecord from a dictionary.

        Args:
            data: Dictionary representation of a run record.

        Returns:
            RunRecord instance.
        """
        return cls(
            run_id=data.get("run_id", uuid.uuid4().hex),
            ticket_id=data.get("ticket_id", ""),
            ticket_title=data.get("ticket_title", ""),
            started_at=data.get("started_at", ""),
            finished_at=data.get("finished_at"),
            duration_seconds=data.get("duration_seconds"),
            mode=data.get("mode", "live"),
            status=data.get("status", "running"),
            verdict=data.get("verdict"),
            plan=data.get("plan"),
            modified_files=data.get("modified_files", []),
            tests_executed=data.get("tests_executed", 0),
            tests_passed=data.get("tests_passed", 0),
            tests_failed=data.get("tests_failed", 0),
            logs=data.get("logs", []),
            errors=data.get("errors", []),
            evidence=data.get("evidence", []),
            tokens_used=data.get("tokens_used"),
            cost_usd=data.get("cost_usd"),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def validate(cls, data: dict) -> list[str]:
        """Validate a run record dictionary.

        Args:
            data: Dictionary to validate.

        Returns:
            List of warning messages (empty if valid).
        """
        warnings = []
        required_fields = ["run_id", "ticket_id", "started_at", "status"]
        for field_name in required_fields:
            if field_name not in data:
                warnings.append(f"Missing required field: {field_name}")

        valid_statuses = ["running", "completed", "failed", "cancelled"]
        if data.get("status") not in valid_statuses:
            warnings.append(f"Invalid status: {data.get('status')!r}")

        valid_verdicts = [None, "PASS", "PASS_WITH_OBS", "FAIL", "BLOCKED"]
        if data.get("verdict") not in valid_verdicts:
            warnings.append(f"Invalid verdict: {data.get('verdict')!r}")

        return warnings
