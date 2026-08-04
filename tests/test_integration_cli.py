"""Integration tests for end-to-end CLI commands.

Validates: Requirements 1.1, 1.7, 1.8

Tests the CLI interface end-to-end using Click's CliRunner to verify:
- Command invocation and exit codes
- Error messages for missing arguments
- Help output includes all commands
- Config outputs text
- Work command behavior with and without ticket-id
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from autopilot.cli.commands import cli
from autopilot.domain.entities.config import Config
from autopilot.infrastructure.persistence.file_lock import LedgerLock, lock_path_for


def test_cli_no_command_shows_help_with_nonzero_exit():
    """Invoking CLI with no command shows help and exits with non-zero code.

    Validates: Requirement 1.7 (non-zero exit on failure)
    """
    runner = CliRunner()
    result = runner.invoke(cli, [])

    assert result.exit_code != 0
    # Help output should mention available commands
    assert "work" in result.output
    assert "config" in result.output
    assert "status" in result.output


def test_cli_work_without_ticket_id_shows_error():
    """Invoking 'work' without ticket-id shows error and exits non-zero.

    Validates: Requirement 1.8
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["work"])

    assert result.exit_code != 0
    # Click should show an error about the missing TICKET_ID argument
    output = result.output.lower()
    assert "ticket_id" in output or "ticket-id" in output or "missing" in output


def test_cli_work_with_ticket_id_without_config_shows_error():
    """Invoking 'work TICKET-123' without config.yaml shows failure gracefully.

    Validates: Requirement 1.1, 1.7
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["work", "TICKET-123", "--config-path", "/nonexistent/config.yaml"])

    # Should exit non-zero because config doesn't exist
    assert result.exit_code != 0
    # Should show an error message (not a traceback crash)
    output = result.output.lower()
    assert "fail" in output or "error" in output or "config" in output


def test_cli_work_accepts_ticket_id_argument():
    """Invoking 'work' with a ticket-id argument is accepted by Click.

    Validates: Requirement 1.1
    """
    runner = CliRunner()
    # Even if workflow fails (no config), the CLI accepts the argument
    result = runner.invoke(cli, ["work", "TICKET-123", "--config-path", "/nonexistent.yaml"])

    # Should not complain about missing arguments
    assert "missing" not in result.output.lower() or "config" in result.output.lower()


def test_cli_config_without_config_file_shows_error():
    """Invoking 'config' without a valid config.yaml shows error gracefully.

    Validates: Requirement 1.7
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "--config-path", "/nonexistent/config.yaml"])

    # Should exit non-zero and show an error, not crash
    assert result.exit_code != 0


def test_cli_status_succeeds():
    """Invoking 'status' exits with code 0.

    Validates: Requirement 1.7
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["status"])

    assert result.exit_code == 0


def test_cli_review_succeeds():
    """Invoking 'review' exits with code 0.

    Validates: Requirement 1.7
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["review"])

    assert result.exit_code == 0


def test_cli_help_shows_all_commands():
    """Invoking '--help' shows all registered commands.

    Validates: Requirement 1.7
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    # All defined commands should appear in help output
    assert "work" in result.output
    assert "status" in result.output
    assert "resume" in result.output
    assert "config" in result.output
    assert "review" in result.output


# ---------------------------------------------------------------------------
# config_sanity_validator CLI wiring tests
#
# Feature: safe-persistence-and-config-validation
# Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7
# ---------------------------------------------------------------------------


def _make_valid_config(tmp_path):
    workspace = str(tmp_path / "workspace")
    return Config(vault_location=str(tmp_path / "vault"), workspace_location=workspace)


def _make_mock_app(config):
    app = MagicMock()
    app.config = config
    app.config_command.execute.return_value = "vault_location: /tmp\n"
    app.ledger.summary.return_value = "summary"
    app.ledger.get_by_ticket.return_value = []
    app.resume_command.execute.return_value = "some-execution-id"
    return app


@pytest.mark.parametrize(
    "command_args,main_action_attr",
    [
        (["config"], "config_command.execute"),
        (["ledger"], "ledger.summary"),
        (["resume"], "resume_command.execute"),
    ],
)
def test_cli_command_blank_workspace_aborts_before_main_action(command_args, main_action_attr, tmp_path):
    """Invalid Config (blank workspace_location) aborts with non-zero exit and
    never invokes the command's main action.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.5**
    """
    config = Config(vault_location=str(tmp_path / "vault"), workspace_location="   ")
    app = _make_mock_app(config)

    with patch("autopilot.infrastructure.bootstrap.create_application", return_value=app):
        runner = CliRunner()
        result = runner.invoke(cli, command_args)

    assert result.exit_code != 0

    obj, attr = main_action_attr.split(".")
    getattr(getattr(app, obj), attr).assert_not_called()


@pytest.mark.parametrize(
    "command_args,main_action_attr",
    [
        (["config"], "config_command.execute"),
        (["ledger"], "ledger.summary"),
        (["resume"], "resume_command.execute"),
    ],
)
def test_cli_command_blank_vault_aborts_before_main_action(command_args, main_action_attr, tmp_path):
    """Invalid Config (blank vault_location) aborts with non-zero exit and
    never invokes the command's main action.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.5**
    """
    config = Config(vault_location="   ", workspace_location=str(tmp_path / "workspace"))
    app = _make_mock_app(config)

    with patch("autopilot.infrastructure.bootstrap.create_application", return_value=app):
        runner = CliRunner()
        result = runner.invoke(cli, command_args)

    assert result.exit_code != 0

    obj, attr = main_action_attr.split(".")
    getattr(getattr(app, obj), attr).assert_not_called()


@pytest.mark.parametrize(
    "command_args,main_action_attr",
    [
        (["config"], "config_command.execute"),
        (["ledger"], "ledger.summary"),
        (["resume"], "resume_command.execute"),
    ],
)
def test_cli_command_non_creatable_workspace_aborts_before_main_action(
    command_args, main_action_attr, tmp_path
):
    """Invalid Config (non-creatable workspace_location, occupied by a file)
    aborts with non-zero exit and never invokes the command's main action.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.5**
    """
    occupied = tmp_path / "occupied_by_file"
    occupied.write_text("not a directory")
    config = Config(vault_location=str(tmp_path / "vault"), workspace_location=str(occupied))
    app = _make_mock_app(config)

    with patch("autopilot.infrastructure.bootstrap.create_application", return_value=app):
        runner = CliRunner()
        result = runner.invoke(cli, command_args)

    assert result.exit_code != 0

    obj, attr = main_action_attr.split(".")
    getattr(getattr(app, obj), attr).assert_not_called()


@pytest.mark.parametrize(
    "command_args,main_action_attr",
    [
        (["config"], "config_command.execute"),
        (["ledger"], "ledger.summary"),
        (["resume"], "resume_command.execute"),
    ],
)
def test_cli_command_valid_config_invokes_main_action(command_args, main_action_attr, tmp_path):
    """Valid Config passes the sanity check and the command's main action
    is invoked.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.6**
    """
    config = _make_valid_config(tmp_path)
    app = _make_mock_app(config)

    with patch("autopilot.infrastructure.bootstrap.create_application", return_value=app):
        runner = CliRunner()
        runner.invoke(cli, command_args)

    obj, attr = main_action_attr.split(".")
    getattr(getattr(app, obj), attr).assert_called_once()


def test_cli_work_blank_workspace_aborts_before_workflow_execution(tmp_path):
    """Invalid Config (blank workspace) for `work` aborts before workflow
    execution, and before validate_environment.

    **Validates: Requirements 5.4, 5.5**
    """
    config = Config(vault_location=str(tmp_path / "vault"), workspace_location="   ")
    app = _make_mock_app(config)

    with patch("autopilot.infrastructure.bootstrap.create_application", return_value=app), \
         patch("autopilot.infrastructure.validators.validate_environment") as mock_validate_env:
        runner = CliRunner()
        result = runner.invoke(cli, ["work", "TICKET-1"])

    assert result.exit_code != 0
    app.work_command.execute.assert_not_called()
    mock_validate_env.assert_not_called()


def test_cli_work_skip_validation_with_invalid_config_still_aborts_from_sanity_check(tmp_path):
    """With --skip-validation and a sanity-invalid Config, `work` still exits
    non-zero from the sanity check, and validate_environment never runs.

    **Validates: Requirements 5.7**
    """
    config = Config(vault_location=str(tmp_path / "vault"), workspace_location="   ")
    app = _make_mock_app(config)

    with patch("autopilot.infrastructure.bootstrap.create_application", return_value=app), \
         patch("autopilot.infrastructure.validators.validate_environment") as mock_validate_env:
        runner = CliRunner()
        result = runner.invoke(cli, ["work", "TICKET-1", "--skip-validation"])

    assert result.exit_code != 0
    app.work_command.execute.assert_not_called()
    mock_validate_env.assert_not_called()


def test_cli_work_skip_validation_with_valid_config_skips_validate_environment_only(tmp_path):
    """With --skip-validation and a sanity-valid Config, config_sanity_validator
    runs but validate_environment does not.

    **Validates: Requirements 5.7**
    """
    config = _make_valid_config(tmp_path)
    app = _make_mock_app(config)
    app.work_command.execute.return_value = MagicMock(
        run_id="abc123def456", mode="dry-run", status="completed", verdict="PASS",
        tests_executed=0, tests_passed=0, tests_failed=0, modified_files=[], errors=[],
    )

    with patch("autopilot.infrastructure.bootstrap.create_application", return_value=app), \
         patch(
             "autopilot.infrastructure.validators.config_sanity_validator",
             wraps=__import__(
                 "autopilot.infrastructure.validators", fromlist=["config_sanity_validator"]
             ).config_sanity_validator,
         ) as mock_sanity, \
         patch("autopilot.infrastructure.validators.validate_environment") as mock_validate_env:
        runner = CliRunner()
        runner.invoke(cli, ["work", "TICKET-1", "--skip-validation", "--dry-run"])

    mock_sanity.assert_called_once()
    mock_validate_env.assert_not_called()


# ---------------------------------------------------------------------------
# Per-workspace run lock tests (`work` / `resume` must not race on the same
# workspace's state file / git branch)
# ---------------------------------------------------------------------------


def test_cli_work_aborts_when_workspace_run_lock_already_held(tmp_path):
    """If another process already holds the per-workspace run lock, `work`
    exits non-zero with a clear message and never calls work_command.execute."""
    config = _make_valid_config(tmp_path)
    app = _make_mock_app(config)

    run_lock_path = lock_path_for(os.path.join(config.workspace_location, ".autopilot_run"))

    with LedgerLock(run_lock_path):
        with patch("autopilot.infrastructure.bootstrap.create_application", return_value=app), \
             patch("autopilot.infrastructure.validators.validate_environment"):
            runner = CliRunner()
            result = runner.invoke(cli, ["work", "TICKET-1", "--skip-validation"])

    assert result.exit_code != 0
    assert "ya hay un run" in result.output.lower()
    app.work_command.execute.assert_not_called()


def test_cli_resume_aborts_when_workspace_run_lock_already_held(tmp_path):
    """If another process already holds the per-workspace run lock, `resume`
    exits non-zero and never calls resume_command.execute."""
    config = _make_valid_config(tmp_path)
    app = _make_mock_app(config)

    run_lock_path = lock_path_for(os.path.join(config.workspace_location, ".autopilot_run"))

    with LedgerLock(run_lock_path):
        with patch("autopilot.infrastructure.bootstrap.create_application", return_value=app):
            runner = CliRunner()
            result = runner.invoke(cli, ["resume"])

    assert result.exit_code != 0
    assert "ya hay un run" in result.output.lower()
    app.resume_command.execute.assert_not_called()


def test_cli_work_releases_run_lock_after_success(tmp_path):
    """After a successful `work` run, the run lock is released so a
    subsequent invocation can acquire it."""
    config = _make_valid_config(tmp_path)
    app = _make_mock_app(config)
    app.work_command.execute.return_value = MagicMock(
        run_id="abc123def456", mode="dry-run", status="completed", verdict="PASS",
        tests_executed=0, tests_passed=0, tests_failed=0, modified_files=[], errors=[],
    )

    with patch("autopilot.infrastructure.bootstrap.create_application", return_value=app), \
         patch("autopilot.infrastructure.validators.validate_environment"):
        runner = CliRunner()
        result = runner.invoke(cli, ["work", "TICKET-1", "--skip-validation", "--dry-run"])

    assert result.exit_code == 0

    run_lock_path = lock_path_for(os.path.join(config.workspace_location, ".autopilot_run"))
    # A fresh non-blocking acquisition must succeed — proves the lock was released.
    with LedgerLock(run_lock_path, blocking=False):
        pass
