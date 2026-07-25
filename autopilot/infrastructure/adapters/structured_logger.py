"""Structured logger for workflow execution observability."""

import json
import sys
from typing import Any


def _truncate_dict(data: dict, max_str_len: int = 100) -> dict:
    """Truncate long string values in a dict for display."""
    result = {}
    for k, v in data.items():
        if isinstance(v, str) and len(v) > max_str_len:
            result[k] = v[:max_str_len] + "..."
        elif isinstance(v, list) and len(v) > 5:
            result[k] = v[:5] + [f"... ({len(v) - 5} more)"]
        else:
            result[k] = v
    return result


class StructuredLogger:
    """Logger that emits structured agent execution output to the terminal.

    Supports verbosity levels:
    - quiet: only errors and final summary
    - normal: agent start/completion entries
    - verbose: additionally input/output data
    """

    VALID_VERBOSITY_LEVELS = ("quiet", "normal", "verbose")

    def __init__(self, verbosity: str = "normal", log_dir: str | None = None) -> None:
        """Initialize the structured logger.

        Args:
            verbosity: One of "quiet", "normal", or "verbose".
            log_dir: Optional directory path for writing execution log files.

        Raises:
            ValueError: If verbosity is not a valid level.
        """
        if verbosity not in self.VALID_VERBOSITY_LEVELS:
            raise ValueError(
                f"Invalid verbosity '{verbosity}'. "
                f"Must be one of: {', '.join(self.VALID_VERBOSITY_LEVELS)}"
            )
        self._verbosity = verbosity
        self._log_dir = log_dir

    @property
    def verbosity(self) -> str:
        """Return the current verbosity level."""
        return self._verbosity

    @property
    def log_dir(self) -> str | None:
        """Return the configured log directory."""
        return self._log_dir

    def log_agent_start(self, agent_name: str, action: str, details: dict | None = None) -> None:
        """Emit a log entry when an agent begins execution.

        Format: [Agent_Name] action description

        Only emitted at normal and verbose levels.

        Args:
            agent_name: The registered agent name.
            action: Description of the action being performed.
            details: Optional additional details to display.
        """
        if self._verbosity in ("normal", "verbose"):
            print(f"  ▶ [{agent_name}] {action}")
            if details and self._verbosity == "verbose":
                for k, v in details.items():
                    if v:
                        print(f"    {k}: {str(v)[:100]}")

    def log_agent_completion(
        self,
        agent_name: str,
        elapsed_ms: int,
        status: str,
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
        summary: str | None = None,
    ) -> None:
        """Emit a log entry when an agent completes execution.

        Includes agent name, elapsed time in milliseconds, and status.
        Errors are always emitted regardless of verbosity level.
        At verbose level, input/output data is also printed.

        Args:
            agent_name: The registered agent name.
            elapsed_ms: Execution time in milliseconds.
            status: One of "success", "failed", or "skipped".
            input_data: Optional input data (shown at verbose level).
            output_data: Optional output data (shown at verbose level).
            summary: Optional summary string to display.
        """
        is_error = status == "failed"

        if is_error or self._verbosity in ("normal", "verbose"):
            if status == "success":
                symbol = "✓"
                color_code = "\033[32m"  # green
            elif status == "failed":
                symbol = "✗"
                color_code = "\033[31m"  # red
            else:
                symbol = "○"
                color_code = "\033[33m"  # yellow
            reset = "\033[0m"
            print(f"  {color_code}{symbol}{reset} [{agent_name}] {status} ({elapsed_ms}ms)")
            if summary:
                print(f"    {summary}")

        if self._verbosity == "verbose":
            if input_data is not None:
                print(f"    input: {input_data}")
            if output_data is not None:
                print(f"    output: {_truncate_dict(output_data)}")

    def log_retry(
        self,
        agent_name: str,
        attempt: int,
        max_attempts: int,
        error: str,
    ) -> None:
        """Emit a log entry for a retry attempt.

        Always emitted regardless of verbosity level since retries indicate issues.

        Args:
            agent_name: The registered agent name.
            attempt: Current attempt number.
            max_attempts: Maximum number of attempts allowed.
            error: Description of the error that triggered the retry.
        """
        print(
            f"[{agent_name}] retry {attempt}/{max_attempts} — {error}",
            file=sys.stderr,
        )

    def log_warning(self, message: str) -> None:
        """Emit a warning log entry.

        Always emitted regardless of verbosity level, since warnings
        indicate conditions the user should be aware of (e.g. a
        non-fatal persistence failure).

        Args:
            message: The warning message to display.
        """
        print(f"  ⚠ {message}", file=sys.stderr)

    def log_summary(
        self,
        total_duration_ms: int,
        steps_executed: int,
        steps_failed: int,
        steps_skipped: int,
    ) -> None:
        """Emit a final workflow summary.

        Always emitted regardless of verbosity level.

        Args:
            total_duration_ms: Total workflow duration in milliseconds.
            steps_executed: Number of steps that were executed.
            steps_failed: Number of steps with failed status.
            steps_skipped: Number of steps with skipped status.
        """
        print(
            f"\n  Summary: {total_duration_ms}ms total | "
            f"{steps_executed} executed | "
            f"{steps_failed} failed | "
            f"{steps_skipped} skipped"
        )

    def write_execution_log(
        self, log_entries: list[dict[str, Any]], filepath: str
    ) -> dict[str, Any] | None:
        """Write execution log entries to a JSON file.

        On filesystem write failure, prints a warning to stderr and returns
        error information instead of crashing.

        Args:
            log_entries: List of log entry dictionaries to persist.
            filepath: Path to write the JSON log file.

        Returns:
            None on success, or a dict with error information on failure.
        """
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(log_entries, f, indent=2, default=str)
            return None
        except (IOError, OSError) as exc:
            error_info = {
                "error_type": "filesystem_write_failure",
                "description": f"Failed to write execution log to {filepath}: {exc}",
                "filepath": filepath,
            }
            print(
                f"Warning: {error_info['description']}",
                file=sys.stderr,
            )
            return error_info
