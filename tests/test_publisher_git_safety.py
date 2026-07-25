"""Property and unit tests for PublisherAgent git shell-injection fix.

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.1-2.7, 3.1-3.4, 4.1-4.3,
5.2-5.5, 5.7, 5.8
"""

from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from autopilot.infrastructure.agents.publisher import PublisherAgent


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

title_strategy = st.text(min_size=0, max_size=200)
message_strategy = st.text(min_size=0, max_size=200)
args_list_strategy = st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=5)


# ---------------------------------------------------------------------------
# Property 3-8: Branch slug sanitization
# Validates: Requirements 2.1-2.7
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(title=title_strategy)
def test_branch_slug_has_no_uppercase(title: str):
    """Feature: publisher-shell-injection-fix, Property 3: Branch slugs
    contain no uppercase ASCII letters."""
    slug = PublisherAgent._sanitize_branch_slug(title)
    assert not any(c.isascii() and c.isupper() for c in slug)


@settings(max_examples=100)
@given(title=title_strategy)
def test_branch_slug_charset(title: str):
    """Feature: publisher-shell-injection-fix, Property 4: Branch slugs use
    only lowercase alphanumerics and hyphens."""
    slug = PublisherAgent._sanitize_branch_slug(title)
    assert all(c in "0123456789-abcdefghijklmnopqrstuvwxyz" for c in slug)


@settings(max_examples=100)
@given(title=title_strategy)
def test_branch_slug_no_consecutive_hyphens(title: str):
    """Feature: publisher-shell-injection-fix, Property 5: no consecutive
    hyphens."""
    slug = PublisherAgent._sanitize_branch_slug(title)
    assert "--" not in slug


@settings(max_examples=100)
@given(title=title_strategy)
def test_branch_slug_no_leading_trailing_hyphen(title: str):
    """Feature: publisher-shell-injection-fix, Property 6: no leading or
    trailing hyphen."""
    slug = PublisherAgent._sanitize_branch_slug(title)
    assert not slug.startswith("-")
    assert not slug.endswith("-")


@settings(max_examples=100)
@given(
    title=st.text(
        alphabet=st.sampled_from(" \t!@#$%^&*()_+=[]{}|\\:;\"'<>,.?/~"),
        min_size=0,
        max_size=50,
    )
)
def test_branch_slug_empty_falls_back(title: str):
    """Feature: publisher-shell-injection-fix, Property 7: titles that
    sanitize to nothing fall back to 'implementation'."""
    slug = PublisherAgent._sanitize_branch_slug(title)
    assert slug == "implementation"


@settings(max_examples=100)
@given(title=title_strategy)
def test_branch_slug_max_length(title: str):
    """Feature: publisher-shell-injection-fix, Property 8: branch slugs
    never exceed 30 code points."""
    slug = PublisherAgent._sanitize_branch_slug(title)
    assert len(slug) <= 30


# ---------------------------------------------------------------------------
# Unit tests: _sanitize_branch_slug edge cases
# Validates: Requirements 2.1-2.7
# ---------------------------------------------------------------------------

def test_branch_slug_simple_title():
    assert PublisherAgent._sanitize_branch_slug("Fix Login Bug") == "fix-login-bug"


def test_branch_slug_empty_title():
    assert PublisherAgent._sanitize_branch_slug("") == "implementation"


def test_branch_slug_only_punctuation():
    assert PublisherAgent._sanitize_branch_slug("!!!") == "implementation"


def test_branch_slug_truncates_long_title():
    slug = PublisherAgent._sanitize_branch_slug("a" * 40)
    assert slug == "a" * 30
    assert len(slug) == 30


def test_branch_slug_truncation_lands_on_hyphen():
    # 29 'a' characters followed by a hyphen and more content; the hyphen
    # falls exactly at code point index 29 (0-indexed) after truncation to
    # 30 chars, so the trailing-hyphen trim must remove it.
    title = "a" * 29 + " " + "b" * 10
    slug = PublisherAgent._sanitize_branch_slug(title)
    assert not slug.endswith("-")
    assert len(slug) <= 30


# ---------------------------------------------------------------------------
# Property 9-10: Commit message sanitization
# Validates: Requirements 3.1, 3.2, 3.3
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(message=message_strategy)
def test_commit_message_no_control_chars(message: str):
    """Feature: publisher-shell-injection-fix, Property 9: commit messages
    contain no control characters."""
    sanitized = PublisherAgent._sanitize_commit_message(message)
    assert all((0x20 <= ord(c) < 0x7F) or ord(c) > 0x7F for c in sanitized)
    assert "\n" not in sanitized
    assert "\r" not in sanitized


@settings(max_examples=100)
@given(
    message=st.text(
        alphabet=st.one_of(
            st.characters(min_codepoint=0x00, max_codepoint=0x1F),
            st.just("\x7f"),
            st.just(" "),
        ),
        min_size=0,
        max_size=50,
    )
)
def test_commit_message_empty_falls_back(message: str):
    """Feature: publisher-shell-injection-fix, Property 10: empty or
    whitespace-only sanitized messages fall back to 'Automated commit'."""
    sanitized = PublisherAgent._sanitize_commit_message(message)
    assert sanitized == "Automated commit"


@settings(max_examples=100)
@given(message=message_strategy)
def test_commit_message_never_empty(message: str):
    """Feature: publisher-shell-injection-fix, Property 10: sanitized
    commit message is never the empty string."""
    sanitized = PublisherAgent._sanitize_commit_message(message)
    assert sanitized != ""


# ---------------------------------------------------------------------------
# Unit tests: _sanitize_commit_message edge cases
# Validates: Requirements 3.1, 3.2, 3.3
# ---------------------------------------------------------------------------

def test_commit_message_strips_crlf():
    assert PublisherAgent._sanitize_commit_message("feat: add x\r\ny") == "feat: add xy"


def test_commit_message_all_control_chars_falls_back():
    assert PublisherAgent._sanitize_commit_message("\x00\x01\x1f\x7f") == "Automated commit"


def test_commit_message_whitespace_only_falls_back():
    assert PublisherAgent._sanitize_commit_message("   ") == "Automated commit"


# ---------------------------------------------------------------------------
# Property 1, 2, 11-16: git command construction and stop-on-failure workflow
# Validates: Requirements 1.1, 1.3, 1.4, 3.4, 4.1, 4.2, 4.3, 5.2, 5.3, 5.4,
# 5.5, 5.7, 5.8
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(args=args_list_strategy)
def test_git_cmd_invokes_subprocess_without_shell(args: list[str]):
    """Feature: publisher-shell-injection-fix, Property 1: subprocess.run is
    invoked without a shell."""
    agent = PublisherAgent(tool_registry=MagicMock())
    results = {"operations": []}
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        agent._git_cmd(args, results)
        called_args, called_kwargs = mock_run.call_args
        assert called_args[0] == ["git", *args]
        assert called_kwargs["shell"] is False


@settings(max_examples=100)
@given(args=args_list_strategy)
def test_git_cmd_logs_exact_arg_list(args: list[str]):
    """Feature: publisher-shell-injection-fix, Property 2: operations log
    stores the exact argument list."""
    agent = PublisherAgent(tool_registry=MagicMock())
    results = {"operations": []}
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        agent._git_cmd(args, results)
        assert results["operations"][-1]["command"] == ["git", *args]


@settings(max_examples=100)
@given(returncode=st.integers(min_value=-5, max_value=5))
def test_git_cmd_success_matches_returncode(returncode: int):
    """Feature: publisher-shell-injection-fix, Property 13: logged success
    reflects the exit code."""
    agent = PublisherAgent(tool_registry=MagicMock())
    results = {"operations": []}
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=returncode, stdout="", stderr="")
        agent._git_cmd(["status"], results)
        assert results["operations"][-1]["success"] == (returncode == 0)


@settings(max_examples=100)
@given(
    stdout=st.text(max_size=50),
    stderr=st.text(max_size=50),
)
def test_git_cmd_output_matches_stdout_or_stderr(stdout: str, stderr: str):
    """Feature: publisher-shell-injection-fix, Property 14: logged output
    reflects captured stdout/stderr."""
    agent = PublisherAgent(tool_registry=MagicMock())
    results = {"operations": []}
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=stdout, stderr=stderr)
        agent._git_cmd(["status"], results)
        expected = stdout.strip() or stderr.strip()
        assert results["operations"][-1]["output"] == expected


@settings(max_examples=100)
@given(
    title=st.text(min_size=1, max_size=100),
    fail_index=st.integers(min_value=0, max_value=5),
)
def test_workflow_stops_on_first_failure(title: str, fail_index: int):
    """Feature: publisher-shell-injection-fix, Property 12: workflow stops
    at the first failing step. Property 15: branch is always populated.
    Property 16: commit_message presence matches whether attempted."""
    agent = PublisherAgent(tool_registry=MagicMock())
    ticket = {"title": title}
    rules = {
        "branch_from": "develop",
        "branch_pattern": "feature/{ticket_id}-{description}",
        "commit_pattern": "feat({ticket_id}): {description}",
        "push_remote": "origin",
    }
    call_count = 0

    def fake_run(cmd, **kwargs):
        nonlocal call_count
        step = call_count
        call_count += 1
        rc = 1 if step == fail_index else 0
        return MagicMock(returncode=rc, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        results = agent._execute_git_workflow("TICKET-1", ticket, rules)

    assert len(results["operations"]) == fail_index + 1
    assert "branch" in results
    commit_step_index = 4
    if fail_index >= commit_step_index:
        assert "commit_message" in results
    else:
        assert "commit_message" not in results


@settings(max_examples=100)
@given(message=st.text(min_size=1, max_size=50))
def test_commit_step_message_is_distinct_arg(message: str):
    """Feature: publisher-shell-injection-fix, Property 11: commit message
    is a distinct argument element."""
    agent = PublisherAgent(tool_registry=MagicMock())
    results = {"operations": []}
    sanitized = PublisherAgent._sanitize_commit_message(message)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        agent._git_cmd(["commit", "-m", sanitized], results)
        command = results["operations"][-1]["command"]
        m_index = command.index("-m")
        assert command[m_index + 1] == sanitized


# ---------------------------------------------------------------------------
# Unit tests: _execute_git_workflow scenarios
# Validates: Requirements 1.1, 1.2, 4.1, 4.2, 4.3, 5.5, 5.7, 5.8
# ---------------------------------------------------------------------------

def _default_workflow_rules():
    return {
        "branch_from": "develop",
        "branch_pattern": "feature/{ticket_id}-{description}",
        "commit_pattern": "feat({ticket_id}): {description}",
        "push_remote": "origin",
    }


def test_execute_git_workflow_all_steps_succeed():
    agent = PublisherAgent(tool_registry=MagicMock())
    ticket = {"title": "Fix Login Bug"}
    rules = _default_workflow_rules()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        results = agent._execute_git_workflow("TICKET-1", ticket, rules)

    assert len(results["operations"]) == 6
    assert results["branch"] == "feature/ticket-1-fix-login-bug"
    assert "commit_message" in results
    assert all(op["success"] for op in results["operations"])


def test_execute_git_workflow_source_checkout_fails():
    agent = PublisherAgent(tool_registry=MagicMock())
    ticket = {"title": "Fix Login Bug"}
    rules = _default_workflow_rules()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        results = agent._execute_git_workflow("TICKET-1", ticket, rules)

    assert len(results["operations"]) == 1
    assert "branch" in results
    assert "commit_message" not in results


def test_execute_git_workflow_neutralizes_shell_metacharacters():
    agent = PublisherAgent(tool_registry=MagicMock())
    ticket = {"title": "fix `rm -rf /` bug"}
    rules = _default_workflow_rules()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        results = agent._execute_git_workflow("TICKET-1", ticket, rules)

    branch_name = results["branch"]
    assert "`" not in branch_name
    assert ";" not in branch_name
    assert "$" not in branch_name
    assert " " not in branch_name

    checkout_branch_call = mock_run.call_args_list[2]
    called_args = checkout_branch_call[0][0]
    assert called_args == ["git", "checkout", "-b", branch_name]
    assert called_args[-1] == branch_name
