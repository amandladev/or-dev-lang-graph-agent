"""Integration tests for end-to-end CLI commands.

Validates: Requirements 1.1, 1.7, 1.8

Tests the CLI interface end-to-end using Click's CliRunner to verify:
- Command invocation and exit codes
- Error messages for missing arguments
- Help output includes all commands
- Config outputs text
- Work command behavior with and without ticket-id
"""

from click.testing import CliRunner

from autopilot.cli.commands import cli


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


def test_cli_work_with_ticket_id_succeeds():
    """Invoking 'work TICKET-123' succeeds with exit code 0.

    Validates: Requirement 1.1
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["work", "TICKET-123"])

    assert result.exit_code == 0
    # Output should contain the workflow execution info
    assert "Workflow" in result.output or "workflow" in result.output


def test_cli_config_outputs_text():
    """Invoking 'config' outputs non-empty text and exits with code 0.

    Validates: Requirement 1.7
    """
    runner = CliRunner()
    result = runner.invoke(cli, ["config"])

    assert result.exit_code == 0
    assert len(result.output.strip()) > 0


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
