"""Tests for TesterAgent with mocked subprocess execution.

Covers Requirement 5 of core-orchestration-test-coverage.
"""

import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from autopilot.domain.value_objects.exceptions import TestFailureError
from autopilot.infrastructure.agents.tester import TesterAgent


# ---------------------------------------------------------------------------
# 5.1 (example): no test framework detected -> skipped, no subprocess.run call
# Validates: Requirements 5.1
# ---------------------------------------------------------------------------


def test_no_test_framework_detected_returns_skipped_and_no_subprocess_call(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    agent = TesterAgent(tool_registry=MagicMock())

    with patch("autopilot.infrastructure.agents.tester.subprocess.run") as mock_run:
        output = agent.execute({"modified_files": []})

    evidence = output["evidence"]
    assert len(evidence) == 1
    assert evidence[0]["data"]["status"] == "skipped"
    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# 5.2 (example): pyproject.toml present + subprocess zero exit -> passed
# Validates: Requirements 5.2
# ---------------------------------------------------------------------------


def test_pyproject_present_zero_exit_returns_passed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    agent = TesterAgent(tool_registry=MagicMock())

    with patch("autopilot.infrastructure.agents.tester.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        output = agent.execute({"modified_files": []})

    evidence = output["evidence"]
    assert evidence[0]["data"]["status"] == "passed"


# ---------------------------------------------------------------------------
# Property 18: Non-zero test-runner exit codes surface as a matching failure
# message
# Validates: Requirements 5.3
# ---------------------------------------------------------------------------


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(exit_code=st.integers(min_value=1, max_value=255))
def test_non_zero_exit_code_raises_test_failure_error_with_exit_code(exit_code: int):
    """Feature: core-orchestration-test-coverage, Property 18: Non-zero
    test-runner exit codes surface as a matching failure message.

    **Validates: Requirements 5.3**
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
        agent = TesterAgent(tool_registry=MagicMock())

        with patch("autopilot.infrastructure.agents.tester.Path.cwd", return_value=tmp_path):
            with patch(
                "autopilot.infrastructure.agents.tester.subprocess.run"
            ) as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=exit_code, stdout="", stderr="fail"
                )
                with pytest.raises(TestFailureError) as exc_info:
                    agent.execute({"modified_files": []})

    assert str(exit_code) in str(exc_info.value)


# ---------------------------------------------------------------------------
# 5.4 (edge case): subprocess.run raises TimeoutExpired
# Validates: Requirements 5.4
# ---------------------------------------------------------------------------


def test_run_tests_timeout_expired_returns_failure_with_exit_code_negative_one():
    agent = TesterAgent(tool_registry=MagicMock())
    test_config = {"framework": "pytest", "command": "python3 -m pytest"}

    with patch("autopilot.infrastructure.agents.tester.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="python3 -m pytest", timeout=180)
        result = agent._run_tests(test_config)

    assert result["success"] is False
    assert result["exit_code"] == -1


# ---------------------------------------------------------------------------
# 5.5 (example): package.json declaring a jest test script
# Validates: Requirements 5.5
# ---------------------------------------------------------------------------


def test_package_json_jest_test_script_parses_jest_framework(tmp_path):
    package_json = tmp_path / "package.json"
    package_json.write_text(json.dumps({"scripts": {"test": "jest --ci"}}))
    agent = TesterAgent(tool_registry=MagicMock())

    config = agent._parse_node_test_config(package_json)

    assert config["framework"] == "jest"
    assert config["command"] == "npm test"


# ---------------------------------------------------------------------------
# 5.6 (example): Makefile containing a "test:" line
# Validates: Requirements 5.6
# ---------------------------------------------------------------------------


def test_makefile_with_test_target_detects_make_framework(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n")
    agent = TesterAgent(tool_registry=MagicMock())

    config = agent._detect_test_config()

    assert config["framework"] == "make"
    assert config["command"] == "make test"


# ---------------------------------------------------------------------------
# 5.7 (edge case): subprocess.run raises FileNotFoundError
# Validates: Requirements 5.7
# ---------------------------------------------------------------------------


def test_run_tests_file_not_found_returns_failure_with_exit_code_negative_one():
    agent = TesterAgent(tool_registry=MagicMock())
    test_config = {"framework": "pytest", "command": "python3 -m pytest"}

    with patch("autopilot.infrastructure.agents.tester.subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError("command not found")
        result = agent._run_tests(test_config)

    assert result["success"] is False
    assert result["exit_code"] == -1
