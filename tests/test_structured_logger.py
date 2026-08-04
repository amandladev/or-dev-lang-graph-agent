"""Unit tests for StructuredLogger.

Validates: Requirements 7.1, 7.2, 7.4, 7.6, 7.7, 7.8
"""

import json
import os
import tempfile

import pytest

from autopilot.infrastructure.adapters.structured_logger import StructuredLogger

# ---------------------------------------------------------------------------
# Construction Tests
# ---------------------------------------------------------------------------


class TestConstructor:
    """Test StructuredLogger initialization."""

    def test_default_verbosity_is_normal(self):
        logger = StructuredLogger()
        assert logger.verbosity == "normal"

    def test_accepts_quiet_verbosity(self):
        logger = StructuredLogger(verbosity="quiet")
        assert logger.verbosity == "quiet"

    def test_accepts_verbose_verbosity(self):
        logger = StructuredLogger(verbosity="verbose")
        assert logger.verbosity == "verbose"

    def test_rejects_invalid_verbosity(self):
        with pytest.raises(ValueError, match="Invalid verbosity"):
            StructuredLogger(verbosity="debug")

    def test_accepts_log_dir(self):
        logger = StructuredLogger(log_dir="/tmp/logs")
        assert logger.log_dir == "/tmp/logs"

    def test_log_dir_defaults_to_none(self):
        logger = StructuredLogger()
        assert logger.log_dir is None


# ---------------------------------------------------------------------------
# log_agent_start Tests
# ---------------------------------------------------------------------------


class TestLogAgentStart:
    """Test log_agent_start emits correct format based on verbosity."""

    def test_normal_prints_start_message(self, capsys):
        """Validates: Requirement 7.1"""
        logger = StructuredLogger(verbosity="normal")
        logger.log_agent_start("Planner", "Creating implementation plan")
        captured = capsys.readouterr()
        assert "[Planner] Creating implementation plan" in captured.out

    def test_verbose_prints_start_message(self, capsys):
        """Validates: Requirement 7.1"""
        logger = StructuredLogger(verbosity="verbose")
        logger.log_agent_start("Context_Builder", "Fetching ticket context")
        captured = capsys.readouterr()
        assert "[Context_Builder] Fetching ticket context" in captured.out

    def test_quiet_does_not_print_start_message(self, capsys):
        """Validates: Requirement 7.6"""
        logger = StructuredLogger(verbosity="quiet")
        logger.log_agent_start("Planner", "Creating plan")
        captured = capsys.readouterr()
        assert captured.out == ""


# ---------------------------------------------------------------------------
# log_agent_completion Tests
# ---------------------------------------------------------------------------


class TestLogAgentCompletion:
    """Test log_agent_completion emits correct format based on verbosity."""

    def test_normal_prints_completion_on_success(self, capsys):
        """Validates: Requirement 7.2"""
        logger = StructuredLogger(verbosity="normal")
        logger.log_agent_completion("Planner", 1200, "success")
        captured = capsys.readouterr()
        assert "[Planner]" in captured.out
        assert "1200ms" in captured.out
        assert "success" in captured.out

    def test_quiet_prints_completion_on_failure(self, capsys):
        """Validates: Requirement 7.6 — errors always emitted."""
        logger = StructuredLogger(verbosity="quiet")
        logger.log_agent_completion("Tester", 500, "failed")
        captured = capsys.readouterr()
        assert "[Tester]" in captured.out
        assert "500ms" in captured.out
        assert "failed" in captured.out

    def test_quiet_does_not_print_on_success(self, capsys):
        """Validates: Requirement 7.6"""
        logger = StructuredLogger(verbosity="quiet")
        logger.log_agent_completion("Planner", 1200, "success")
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_verbose_prints_input_output_data(self, capsys):
        """Validates: Requirement 7.6 — verbose shows input/output."""
        logger = StructuredLogger(verbosity="verbose")
        logger.log_agent_completion(
            "Planner",
            800,
            "success",
            input_data={"ticket": "T-123"},
            output_data={"plan": {"steps": []}},
        )
        captured = capsys.readouterr()
        assert "input:" in captured.out
        assert "ticket" in captured.out
        assert "output:" in captured.out
        assert "plan" in captured.out

    def test_normal_does_not_print_input_output_data(self, capsys):
        logger = StructuredLogger(verbosity="normal")
        logger.log_agent_completion(
            "Planner",
            800,
            "success",
            input_data={"ticket": "T-123"},
            output_data={"plan": {}},
        )
        captured = capsys.readouterr()
        assert "input:" not in captured.out
        assert "output:" not in captured.out


# ---------------------------------------------------------------------------
# log_retry Tests
# ---------------------------------------------------------------------------


class TestLogRetry:
    """Test log_retry emits to stderr."""

    def test_retry_emits_to_stderr(self, capsys):
        logger = StructuredLogger(verbosity="quiet")
        logger.log_retry("Code_Executor", 2, 3, "TestFailureError: tests failed")
        captured = capsys.readouterr()
        assert "[Code_Executor]" in captured.err
        assert "retry 2/3" in captured.err
        assert "TestFailureError" in captured.err


# ---------------------------------------------------------------------------
# log_summary Tests
# ---------------------------------------------------------------------------


class TestLogSummary:
    """Test log_summary is always emitted."""

    def test_summary_emitted_at_quiet(self, capsys):
        """Validates: Requirement 7.4"""
        logger = StructuredLogger(verbosity="quiet")
        logger.log_summary(
            total_duration_ms=5000,
            steps_executed=4,
            steps_failed=1,
            steps_skipped=0,
        )
        captured = capsys.readouterr()
        assert "5000ms" in captured.out
        assert "4 executed" in captured.out
        assert "1 failed" in captured.out
        assert "0 skipped" in captured.out

    def test_summary_emitted_at_normal(self, capsys):
        """Validates: Requirement 7.4"""
        logger = StructuredLogger(verbosity="normal")
        logger.log_summary(10000, 6, 0, 2)
        captured = capsys.readouterr()
        assert "10000ms" in captured.out
        assert "6 executed" in captured.out


# ---------------------------------------------------------------------------
# write_execution_log Tests
# ---------------------------------------------------------------------------


class TestWriteExecutionLog:
    """Test write_execution_log JSON file output and graceful failure."""

    def test_writes_json_file_successfully(self):
        """Validates: Requirement 7.7"""
        logger = StructuredLogger(verbosity="normal")
        entries = [
            {"agent_name": "Planner", "elapsed_ms": 100, "status": "success"},
            {"agent_name": "Tester", "elapsed_ms": 200, "status": "failed"},
        ]

        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            filepath = f.name

        try:
            result = logger.write_execution_log(entries, filepath)
            assert result is None

            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            assert data == entries
        finally:
            os.unlink(filepath)

    def test_handles_write_failure_gracefully(self, capsys):
        """Validates: Requirement 7.8"""
        logger = StructuredLogger(verbosity="normal")
        entries = [{"agent_name": "Planner", "status": "success"}]

        result = logger.write_execution_log(entries, "/nonexistent/dir/log.json")

        # Should not crash, should return error info
        assert result is not None
        assert result["error_type"] == "filesystem_write_failure"
        assert "/nonexistent/dir/log.json" in result["description"]

        # Should emit warning to stderr
        captured = capsys.readouterr()
        assert "Warning" in captured.err

    def test_write_failure_returns_filepath(self, capsys):
        """Validates: Requirement 7.8"""
        logger = StructuredLogger(verbosity="normal")
        result = logger.write_execution_log([], "/no/such/path.json")
        assert result is not None
        assert result["filepath"] == "/no/such/path.json"
